"""Session memory operations tool."""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.tools import Tool

from core.chat.chat_store import ChatStore, StoredChatSession
from core.llm.agents import create_agent, generate_response
from core.llm.model_factory import build_model_instance
from core.logger import UnifiedLogger
from core.chat.history_service import ConversationHistoryItem, ChatHistoryContext, ChatHistoryService
from core.memory.session_memory import (
    MEMORY_VECTOR_MIN_SCORE,
    RELATED_SESSION_AUTOMATIC_THRESHOLD,
    RELATED_SESSION_FIELD_WEIGHTS,
    VECTOR_FIELD_TYPES,
    SessionMemoryArtifact,
    SessionMemoryStore,
    build_fts_query,
)
from core.vector import VectorService
from core.vault_state.service import VaultStateService

from .base import BaseTool


logger = UnifiedLogger(tag="memory-ops-tool")

SESSION_SEARCH_FIELD_WEIGHTS = {
    "domain": 0.25,
    "user_intent": 0.15,
    "summary": 0.10,
    "work_product": 0.05,
}
SESSION_LEXICAL_WEIGHT = 0.45
TRANSCRIPT_LEXICAL_WEIGHT = 0.35
SESSION_SEARCH_MIN_SCORE = 0.05


class MemoryOps(BaseTool):
    """Manage session memory."""

    @classmethod
    def get_tool(cls, vault_path: str | None = None):
        """Get the memory operations tool."""

        async def memory_ops(
            ctx: RunContext,
            *,
            operation: str,
            session_id: str = "",
            mode: str = "search",
            query: str = "",
            limit: int | str = 5,
            data: dict[str, Any] | None = None,
            extraction_model: str = "gpt-mini",
        ) -> str:
            """Manage memory extracted from chat sessions.

            :param operation: Operation name.
            :param session_id: Optional explicit session id. Defaults to the active session when available.
            :param mode: Search mode for search_sessions: search, deep, or related. Defaults to search.
            :param query: User-provided search phrase for search and deep modes.
            :param limit: Positive integer result limit for search_sessions.
            :param data: Memory record payload for upsert_session_memory.
            :param extraction_model: Model alias used by extract_session_memory.
            """
            try:
                deps = getattr(ctx, "deps", None)
                requested_session_id = str(session_id or "").strip() or None
                op = (operation or "").strip().lower()
                history_context = ChatHistoryContext.from_deps(deps)
                active_session_id = requested_session_id or history_context.session_id
                active_vault_name = history_context.vault_name
                store = SessionMemoryStore()

                logger.set_sinks(["validation"]).info(
                    "tool_invoked",
                    data={
                        "tool": "memory_ops",
                        "operation": op,
                    },
                )

                resolved_limit = cls._parse_limit(limit)
                if op == "upsert_session_memory":
                    _require(active_vault_name, "vault_name is required")
                    _require(active_session_id, "session_id is required")
                    memory_data = _upsert_data(data)
                    session_memory = store.upsert_session_memory(
                        vault_name=active_vault_name,
                        session_id=active_session_id,
                        title=_session_title(
                            vault_name=active_vault_name,
                            session_id=active_session_id,
                        ),
                        summary=memory_data.get("summary"),
                        domain=memory_data.get("domain"),
                        work_product=memory_data.get("work_product"),
                        user_intent=memory_data.get("user_intent"),
                        named_entities=memory_data.get("named_entities"),
                        metadata=memory_data.get("metadata"),
                    )
                    _maybe_add_artifacts(
                        store,
                        vault_name=active_vault_name,
                        session_id=active_session_id,
                        artifacts=memory_data.get("artifacts"),
                    )
                    indexed_fields = await _maybe_index_session_memory_fields(
                        store,
                        vault_name=active_vault_name,
                        session_id=active_session_id,
                    )
                    refreshed = store.get_session_memory(
                        vault_name=session_memory.vault_name,
                        session_id=session_memory.session_id,
                    )
                    result = {
                        "status": "ok",
                        "operation": op,
                        "indexed_fields": indexed_fields,
                        "session_memory": refreshed.to_dict() if refreshed else None,
                    }
                elif op == "extract_session_memory":
                    _require(active_vault_name, "vault_name is required")
                    _require(active_session_id, "session_id is required")
                    extraction = await _extract_session_memory(
                        vault_name=active_vault_name,
                        session_id=active_session_id,
                        extraction_model=extraction_model,
                    )
                    session_memory = store.upsert_session_memory(
                        vault_name=active_vault_name,
                        session_id=active_session_id,
                        title=extraction["title"],
                        summary=extraction["summary"],
                        domain=extraction["domain"],
                        work_product=extraction["work_product"],
                        user_intent=extraction["user_intent"],
                        named_entities=extraction["named_entities"],
                        metadata={
                            "source": "chat_session_extraction",
                            "extraction_policy": "two_step_summary_intent_then_classification",
                            "extraction_model": extraction_model,
                            "message_count": extraction["message_count"],
                        },
                    )
                    artifact_count = _add_chat_mutation_artifacts(
                        store,
                        vault_name=active_vault_name,
                        session_id=active_session_id,
                    )
                    indexed_fields = await _maybe_index_session_memory_fields(
                        store,
                        vault_name=active_vault_name,
                        session_id=active_session_id,
                    )
                    refreshed = store.get_session_memory(
                        vault_name=session_memory.vault_name,
                        session_id=session_memory.session_id,
                    )
                    result = {
                        "status": "ok",
                        "operation": op,
                        "indexed_fields": indexed_fields,
                        "artifact_count": artifact_count,
                        "extraction": extraction,
                        "session_memory": refreshed.to_dict() if refreshed else None,
                    }
                elif op == "get_session_memory":
                    _require(active_vault_name, "vault_name is required")
                    _require(active_session_id, "session_id is required")
                    session_memory = store.get_session_memory(
                        vault_name=active_vault_name,
                        session_id=active_session_id,
                    )
                    result = {
                        "status": "found" if session_memory else "not_found",
                        "operation": op,
                        "vault_name": active_vault_name,
                        "session_id": active_session_id,
                        "session_memory": session_memory.to_dict()
                        if session_memory
                        else None,
                    }
                elif op == "search_sessions":
                    _require(active_vault_name, "vault_name is required")
                    normalized_mode = str(mode or "")
                    _validate_search_sessions_request(
                        mode=normalized_mode,
                        query=query,
                        resolved_limit=resolved_limit,
                    )
                    resolved_search_limit = resolved_limit if isinstance(resolved_limit, int) else 5
                    result = await _search_sessions(
                        store=store,
                        vault_name=active_vault_name,
                        session_id=active_session_id,
                        mode=normalized_mode,
                        query=query,
                        limit=resolved_search_limit,
                    )
                else:
                    return (
                        "Unknown operation. Available: extract_session_memory, "
                        "upsert_session_memory, "
                        "get_session_memory, search_sessions"
                    )
                if hasattr(result, "to_dict"):
                    result = result.to_dict()
                return json.dumps(result, ensure_ascii=False, indent=2)
            except ModelRetry:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "memory_ops failed",
                    data={
                        "operation": operation,
                        "session_id": session_id,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
                return f"Error performing '{operation}' operation: {exc}"

        return Tool(
            memory_ops,
            name="memory_ops",
            description="Manage session memory.",
        )

    @classmethod
    def get_instructions(cls) -> str:
        """Get usage instructions for session memory access."""
        return """
Session memory field guidance:
- `summary`: short plain-language summary of the whole chat session.
- `domain`: subject area or knowledge area.
- `work_product`: concrete thing the user wanted produced or answered.
- `user_intent`: user's underlying goal or intent after clarification or drift.
- `named_entities`: only named people, organizations, and places.

Use `upsert_session_memory` only when you already have field values to store.
Pass those values in `data`; supported keys are `summary`, `domain`,
`work_product`, `user_intent`, `named_entities`, `artifacts`, and `metadata`.
It persists supplied values; it does not inspect the transcript or infer missing
fields.

Use `search_sessions` for caller-driven lookup across indexed chat-session
memory. `search_sessions` has three modes:
- `search`: default. Searches a user-provided query across all session-memory
  fields.
- `deep`: searches a user-provided query across all session-memory fields and
  raw chat transcripts.
- `related`: compares an already-extracted current or specified session against
  prior sessions using the default compound related-work policy.

Mode selection:
- Use `search` for normal live-chat lookup when the current session does not
  yet have stored memory.
- Use `deep` when the user asks for a broader or transcript-level search.
- Use `related` only when investigating an existing session that already has
  stored memory and you want to find neighboring sessions.

For `search` and `deep`, write `query` as a plain natural-language phrase. Do
not use explicit boolean syntax such as uppercase AND/OR. Use a positive
integer `limit`. Search and deep modes require a query.

For manual writes, include only `data` fields supported by current context.
Leave unknown fields empty.

Full documentation:
- `__virtual_docs__/tools/memory_ops.md`
"""

    @staticmethod
    def _parse_limit(value: int | str) -> int | str:
        if isinstance(value, int):
            if value <= 0:
                raise ValueError("limit must be a positive integer or 'all'")
            return value
        normalized = str(value or "").strip().lower()
        if not normalized or normalized == "all":
            return "all"
        if normalized.isdigit():
            parsed = int(normalized)
            if parsed <= 0:
                raise ValueError("limit must be a positive integer or 'all'")
            return parsed
        raise ValueError("limit must be a positive integer or 'all'")


class _SessionSummaryIntent(BaseModel):
    """First-pass session memory extraction."""

    summary: str = Field(default="")
    user_intent: str = Field(default="")


class _SessionClassification(BaseModel):
    """Second-pass session memory classification."""

    named_entities: str = Field(default="")
    domain: str = Field(default="")
    work_product: str = Field(default="")


def _require(value: object, message: str) -> None:
    if value is None:
        raise ValueError(message)
    if isinstance(value, str) and not value.strip():
        raise ValueError(message)


def _session_title(*, vault_name: str, session_id: str) -> str | None:
    session = ChatStore().get_session(session_id=session_id, vault_name=vault_name)
    return session.title if session is not None else None


def _upsert_data(data: dict[str, Any] | None) -> dict[str, Any]:
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("data must be an object for upsert_session_memory")
    allowed_keys = {
        "summary",
        "domain",
        "work_product",
        "user_intent",
        "named_entities",
        "artifacts",
        "metadata",
    }
    unknown_keys = sorted(set(data) - allowed_keys)
    if unknown_keys:
        joined = ", ".join(unknown_keys)
        raise ValueError(f"Unsupported upsert_session_memory data keys: {joined}")

    parsed = dict(data)
    if parsed.get("metadata") is not None and not isinstance(parsed["metadata"], dict):
        raise ValueError("data.metadata must be an object")
    if parsed.get("artifacts") is not None and not isinstance(parsed["artifacts"], list):
        raise ValueError("data.artifacts must be a list")
    return parsed


def _validate_search_sessions_request(
    *,
    mode: str,
    query: str,
    resolved_limit: int | str,
) -> None:
    normalized_mode = (mode or "search").strip().lower()
    if resolved_limit == "all":
        raise ModelRetry(
            "search_sessions requires a positive integer limit. Retry with a numeric limit such as 5 or 10."
        )
    if normalized_mode in {"search", "deep"} and not str(query or "").strip():
        raise ModelRetry(
            "search_sessions requires a plain natural-language query for search and deep modes."
        )
    if normalized_mode in {"search", "deep"} and _has_boolean_operator(query):
        raise ModelRetry(
            "search_sessions query must be a plain search phrase. Retry without AND/OR; combine related terms with spaces."
        )


def _has_boolean_operator(query: str) -> bool:
    return re.search(r"\b(?:AND|OR)\b", query) is not None


async def _search_sessions(
    *,
    store: SessionMemoryStore,
    vault_name: str,
    session_id: str | None,
    mode: str,
    query: str,
    limit: int,
) -> dict[str, Any]:
    normalized_mode = (mode or "search").strip().lower()
    if normalized_mode not in {"related", "search", "deep"}:
        raise ValueError("mode must be one of: related, search, deep")

    if normalized_mode == "related":
        _require(session_id, "session_id is required for related mode")
        matches = await store.find_related_sessions(
            vault_name=vault_name,
            session_id=session_id,
            vector_service=VectorService(),
            limit=limit,
        )
        return {
            "status": "ok",
            "operation": "search_sessions",
            "mode": normalized_mode,
            "query": {
                "vault_name": vault_name,
                "session_id": session_id,
                "policy": {
                    "weights": RELATED_SESSION_FIELD_WEIGHTS,
                    "automatic_threshold": RELATED_SESSION_AUTOMATIC_THRESHOLD,
                },
            },
            "matches": [match.to_dict() for match in matches],
            "session_memories": [
                match.session_memory.to_dict()
                for match in matches
            ],
        }

    _require(query, "query is required for search and deep modes")
    memory_matches = await _search_session_memory_fields(
        store=store,
        vault_name=vault_name,
        query=query,
        limit=limit,
    )
    if normalized_mode == "deep":
        _merge_transcript_matches(
            memory_matches,
            store=store,
            vault_name=vault_name,
            query=query,
        )
    for candidate in memory_matches.values():
        candidate["evidence"].sort(
            key=lambda item: float(item.get("weighted_score") or 0.0),
            reverse=True,
        )
    ranked_matches = sorted(
        (
            match
            for match in memory_matches.values()
            if float(match.get("score") or 0.0) >= SESSION_SEARCH_MIN_SCORE
        ),
        key=lambda item: (item["score"], len(item["evidence"])),
        reverse=True,
    )[:limit]
    return {
        "status": "ok",
        "operation": "search_sessions",
        "mode": normalized_mode,
        "query": {
            "vault_name": vault_name,
            "value": query,
        },
        "matches": ranked_matches,
    }


async def _search_session_memory_fields(
    *,
    store: SessionMemoryStore,
    vault_name: str,
    query: str,
    limit: int,
) -> dict[str, dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    lexical_matches = store.search_session_memories_fts(
        vault_name=vault_name,
        query=query,
        limit=max(limit * 4, limit),
    )
    for match in lexical_matches:
        memory = match.session_memory
        weighted_score = round(float(match.score or 0.0) * SESSION_LEXICAL_WEIGHT, 6)
        candidate = candidates.setdefault(
            memory.session_id,
            {
                "session_id": memory.session_id,
                "vault_name": memory.vault_name,
                "field_scores": {},
                "session_memory": memory.to_dict(),
                "evidence": [],
            },
        )
        candidate["field_scores"]["session_memory_fts"] = max(
            float(candidate["field_scores"].get("session_memory_fts", 0.0)),
            weighted_score,
        )
        candidate["evidence"].append(
            {
                "source": "session_memory",
                "match_type": "lexical",
                "score": match.score,
                "weighted_score": weighted_score,
                "rank": match.rank,
                "matched_value": None,
            }
        )

    for current_field in VECTOR_FIELD_TYPES:
        matches = await store.search_session_memories_by_field(
            vault_name=vault_name,
            field_type=current_field,
            value=query,
            vector_service=VectorService(),
            limit=max(limit * 3, limit),
            min_score=MEMORY_VECTOR_MIN_SCORE,
            include_direct=False,
        )
        field_weight = SESSION_SEARCH_FIELD_WEIGHTS.get(current_field, 0.5)
        for match in matches:
            memory = match.session_memory
            normalized_score = _normalize_vector_score(float(match.score or 0.0))
            weighted_score = round(normalized_score * field_weight, 6)
            candidate = candidates.setdefault(
                memory.session_id,
                {
                    "session_id": memory.session_id,
                    "vault_name": memory.vault_name,
                    "field_scores": {},
                    "session_memory": memory.to_dict(),
                    "evidence": [],
                },
            )
            candidate["field_scores"][current_field] = max(
                float(candidate["field_scores"].get(current_field, 0.0)),
                weighted_score,
            )
            candidate["evidence"].append(
                {
                    "source": "session_memory",
                    "field_type": current_field,
                    "match_type": match.match_type,
                    "score": match.score,
                    "normalized_score": normalized_score,
                    "weighted_score": weighted_score,
                    "matched_value": _preview_text(memory.field_value(current_field)),
                }
            )
    for candidate in candidates.values():
        candidate["score"] = round(
            min(sum(float(value) for value in candidate["field_scores"].values()), 1.0),
            6,
        )
        del candidate["field_scores"]
        candidate["evidence"].sort(
            key=lambda item: float(item.get("weighted_score") or 0.0),
            reverse=True,
        )
    return candidates


def _merge_transcript_matches(
    candidates: dict[str, dict[str, Any]],
    *,
    store: SessionMemoryStore,
    vault_name: str,
    query: str,
) -> None:
    chat_store = ChatStore()
    fts_query = build_fts_query(query)
    if not fts_query:
        return
    sessions = chat_store.list_sessions(vault_name)
    if not sessions:
        return
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE VIRTUAL TABLE transcript_fts USING fts5(
            session_id UNINDEXED,
            title,
            transcript,
            tokenize = 'unicode61'
        )
        """
    )
    for session in sessions:
        messages = chat_store.get_stored_messages(
            session_id=session.session_id,
            vault_name=vault_name,
        )
        transcript = "\n\n".join(message.content_text for message in messages)
        conn.execute(
            "INSERT INTO transcript_fts(session_id, title, transcript) VALUES (?, ?, ?)",
            (session.session_id, session.title or "", transcript),
        )
    rows = conn.execute(
        """
        SELECT session_id,
               bm25(transcript_fts, 0.0, 0.8, 1.0) AS rank,
               snippet(transcript_fts, 2, '[', ']', '...', 32) AS snippet
        FROM transcript_fts
        WHERE transcript_fts MATCH ?
        ORDER BY rank ASC
        LIMIT ?
        """,
        (fts_query, max(len(sessions), 1)),
    ).fetchall()
    sessions_by_id = {session.session_id: session for session in sessions}
    for row in rows:
        session_id = str(row["session_id"])
        session = sessions_by_id.get(session_id)
        if session is None:
            continue
        memory = store.get_session_memory(
            vault_name=vault_name,
            session_id=session_id,
        )
        transcript_score = _bm25_rank_score(float(row["rank"]))
        if transcript_score <= 0.0:
            continue
        weighted_score = round(transcript_score * TRANSCRIPT_LEXICAL_WEIGHT, 6)
        candidate = candidates.setdefault(
            session_id,
            {
                "session_id": session_id,
                "vault_name": session.vault_name,
                "session_memory": memory.to_dict() if memory else None,
                "chat_session": {
                    "session_id": session_id,
                    "vault_name": session.vault_name,
                    "title": session.title,
                    "created_at": session.created_at,
                    "last_activity_at": session.last_activity_at,
                },
                "evidence": [],
            },
        )
        if memory is not None and candidate.get("session_memory") is None:
            candidate["session_memory"] = memory.to_dict()
        candidate["score"] = round(
            min(float(candidate.get("score") or 0.0) + weighted_score, 1.0),
            6,
        )
        candidate["evidence"].append(
            {
                "source": "chat_transcript",
                "match_type": "lexical",
                "score": round(transcript_score, 6),
                "weighted_score": weighted_score,
                "rank": round(float(row["rank"]), 6),
                "snippet": str(row["snippet"] or ""),
            }
        )


def _preview_text(value: str | None, *, limit: int = 240) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if len(stripped) <= limit:
        return stripped
    return f"{stripped[:limit].rstrip()}..."


def _bm25_rank_score(rank: float) -> float:
    return round(min(abs(rank) / 10.0, 1.0), 6)


def _normalize_vector_score(score: float) -> float:
    if score <= MEMORY_VECTOR_MIN_SCORE:
        return 0.0
    return round((score - MEMORY_VECTOR_MIN_SCORE) / (1.0 - MEMORY_VECTOR_MIN_SCORE), 6)


async def _extract_session_memory(
    *,
    vault_name: str,
    session_id: str,
    extraction_model: str,
) -> dict[str, Any]:
    chat_store = ChatStore()
    session = chat_store.get_session(session_id=session_id, vault_name=vault_name)
    if session is None:
        raise ValueError(f"Unknown chat session: {session_id}")
    history = ChatHistoryService(chat_store=chat_store).get_conversation_history(
        context=ChatHistoryContext(session_id=session_id, vault_name=vault_name),
        scope="session",
        session_id=session_id,
        limit="all",
    )
    if not history.items:
        raise ValueError(f"Chat session has no persisted messages: {session_id}")
    summary_agent = await create_agent(
        model=build_model_instance(extraction_model),
        output_type=_SessionSummaryIntent,
    )
    classification_agent = await create_agent(
        model=build_model_instance(extraction_model),
        output_type=_SessionClassification,
    )
    summary_intent = await generate_response(
        summary_agent,
        _build_first_pass_prompt(session=session, messages=history.items),
    )
    summary_intent_data = summary_intent.model_dump()
    classification = await generate_response(
        classification_agent,
        _build_second_pass_prompt(
            session=session,
            summary_intent=summary_intent_data,
        ),
    )
    classification_data = classification.model_dump()
    return {
        "session_id": session.session_id,
        "vault_name": session.vault_name,
        "title": session.title,
        "summary": summary_intent_data["summary"],
        "user_intent": summary_intent_data["user_intent"],
        "domain": classification_data["domain"],
        "work_product": classification_data["work_product"],
        "named_entities": classification_data["named_entities"],
        "message_count": history.item_count,
    }


def _build_first_pass_prompt(
    *,
    session: StoredChatSession,
    messages: tuple[ConversationHistoryItem, ...],
) -> str:
    transcript = "\n\n".join(
        f"{message.role.upper()} [{message.sequence_index}]:\n{message.content}"
        for message in messages
    )
    title = session.title or ""
    return f"""
Read this AssistantMD chat session and extract only:

- `summary`: a short plain-language summary of the user's work in the session.
- `user_intent`: what the user was trying to accomplish after clarification,
  repetition, or topic drift.

Rules:
- Use only the conversation text and session metadata shown here.
- Focus on the user's real work, not this extraction task.
- Keep both fields concise but specific enough to support later retrieval.
- Return only the structured output.

Session:
- session_id: {session.session_id}
- vault_name: {session.vault_name}
- title: {title}
- created_at: {session.created_at}
- last_activity_at: {session.last_activity_at}

Conversation:
{transcript}
""".strip()


def _build_second_pass_prompt(
    *,
    session: StoredChatSession,
    summary_intent: dict[str, str],
) -> str:
    title = session.title or ""
    return f"""
Extract classification fields from this distilled chat-session summary.

Use only the summary, user intent, and session title below. Do not infer from
the original transcript.

Fields:
- `domain`: the subject area or knowledge area of the user's work.
- `work_product`: the real deliverable, answer, document, artifact, or decision
  the user wanted from the session. Use a concise generalized category or short
  noun phrase, not a full sentence. Prefer labels such as `report draft`,
  `funder email`, `briefing note`, `knowledge base`, `source memos`,
  `workflow script`, `project summary`, `grant tracker`, or `decision note`.
- `named_entities`: only named people, organizations, and places. Use a concise
  comma- or semicolon-separated list of entities central to the summarized work.
  Leave empty if there are none.

Rules:
- Keep fields concise but specific enough to support later retrieval.
- For `work_product`, do not use phrases like `memory entry`,
  `memory record`, or `session memory` unless the user's actual task was
  to build memory-system documentation or code.
- Keep `work_product` under 8 words when possible.
- Return only the structured output.

Session:
- session_id: {session.session_id}
- title: {title}

Summary:
{summary_intent["summary"]}

User intent:
{summary_intent["user_intent"]}
""".strip()


async def _maybe_index_session_memory_fields(
    store: SessionMemoryStore,
    *,
    vault_name: str,
    session_id: str,
) -> int:
    try:
        return await store.index_session_memory_fields(
            vault_name=vault_name,
            session_id=session_id,
            vector_service=VectorService(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "session_memory_field_indexing_skipped",
            data={
                "vault_name": vault_name,
                "session_id": session_id,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        return 0


def _maybe_add_artifacts(
    store: SessionMemoryStore,
    *,
    vault_name: str,
    session_id: str,
    artifacts: list[dict[str, Any]] | None,
) -> None:
    parsed: list[SessionMemoryArtifact] = []
    for raw in artifacts or []:
        path = str(raw.get("path") or "").strip()
        _require(path, "path is required for each artifact")
        parsed.append(
            SessionMemoryArtifact(
                path=path,
                artifact_role=str(raw.get("artifact_role") or raw.get("role") or "file_retrieved"),
                vault_name=vault_name,
                metadata=dict(raw.get("metadata") or {}),
            )
        )
    if parsed:
        store.add_session_artifacts(
            vault_name=vault_name,
            session_id=session_id,
            artifacts=tuple(parsed),
        )


def _add_chat_mutation_artifacts(
    store: SessionMemoryStore,
    *,
    vault_name: str,
    session_id: str,
) -> int:
    """Attach vault files mutated by this chat session to its memory row."""
    try:
        mutations = VaultStateService().list_chat_session_mutations(
            vault_name=vault_name,
            session_id=session_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "session_memory_artifact_population_skipped",
            data={
                "vault_name": vault_name,
                "session_id": session_id,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        return 0

    artifacts_by_key: dict[tuple[str, str], SessionMemoryArtifact] = {}
    for mutation in mutations:
        role = _artifact_role_for_mutation(
            operation=mutation.operation,
            before_exists=mutation.before_exists,
            after_exists=mutation.after_exists,
        )
        key = (mutation.path, role)
        metadata = {
            "source": "task_file_mutation",
            "operation": mutation.operation,
            "task_id": mutation.task_id,
            "task_kind": mutation.task_kind,
            "task_source": mutation.task_source,
            "task_scope": mutation.task_scope,
            "task_label": mutation.task_label,
            "related_path": mutation.related_path,
            "event_sequence": mutation.event_sequence,
            "before_exists": mutation.before_exists,
            "before_hash": mutation.before_hash,
            "after_exists": mutation.after_exists,
            "after_hash": mutation.after_hash,
            "created_at": _datetime_to_text(mutation.created_at),
        }
        artifacts_by_key[key] = SessionMemoryArtifact(
            path=mutation.path,
            artifact_role=role,
            vault_name=vault_name,
            metadata={key: value for key, value in metadata.items() if value is not None},
        )

    artifacts = tuple(artifacts_by_key.values())
    if not artifacts:
        return 0
    store.add_session_artifacts(
        vault_name=vault_name,
        session_id=session_id,
        artifacts=artifacts,
    )
    return len(artifacts)


def _artifact_role_for_mutation(
    *,
    operation: str,
    before_exists: bool,
    after_exists: bool,
) -> str:
    """Return a stable artifact role for one recorded file mutation."""
    normalized_operation = (operation or "").strip().lower()
    if normalized_operation == "move":
        return "moved_to" if after_exists else "moved_from"
    if normalized_operation == "delete" or not after_exists:
        return "deleted"
    if not before_exists and after_exists:
        return "created"
    if before_exists and after_exists:
        return "modified"
    return normalized_operation or "touched"


def _datetime_to_text(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
