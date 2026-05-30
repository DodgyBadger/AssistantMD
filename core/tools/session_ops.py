"""Chat session operations tool."""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.tools import Tool

from core.chat.chat_store import ChatStore, StoredChatSession
from core.constants import (
    SESSION_SUMMARY_CLASSIFICATION_PROMPT,
    SESSION_SUMMARY_SOURCE_SUMMARY_PROMPT,
    SESSION_SUMMARY_INTENT_PROMPT,
)
from core.llm.agents import create_agent, generate_response
from core.llm.model_factory import build_model_instance
from core.logger import UnifiedLogger
from core.chat.history_service import (
    ChatHistoryContext,
    ChatHistoryService,
    ConversationHistoryItem,
    ConversationToolEventItem,
)
from core.memory.session_summary import (
    SUMMARY_VECTOR_MIN_SCORE,
    RELATED_SESSION_AUTOMATIC_THRESHOLD,
    RELATED_SESSION_FIELD_WEIGHTS,
    VECTOR_FIELD_TYPES,
    SESSION_SUMMARY_FIELD_UNSET,
    SessionSummaryArtifact,
    SessionSummaryStore,
    build_fts_query,
)
from core.memory.session_summary_status import session_summary_status
from core.vector import VectorService
from core.vault_state.service import VaultStateService

from .base import BaseTool


logger = UnifiedLogger(tag="session-ops-tool")

SESSION_SEARCH_FIELD_WEIGHTS = {
    "domain": 0.25,
    "user_intent": 0.15,
    "summary": 0.10,
    "work_product": 0.05,
}
SESSION_LEXICAL_WEIGHT = 0.45
TRANSCRIPT_LEXICAL_WEIGHT = 0.35
SESSION_SEARCH_MIN_SCORE = 0.05


class SessionOps(BaseTool):
    """Search and summarize chat sessions."""

    @classmethod
    def get_tool(cls, vault_path: str | None = None):
        """Get the session operations tool."""

        async def session_ops(
            ctx: RunContext,
            *,
            operation: str,
            session_id: str = "",
            mode: str = "search",
            query: str = "",
            limit: int | str = "",
            cursor: str = "",
            summary_status: str = "summarized",
            data: dict[str, Any] | None = None,
            summarization_model: str = "gpt-mini",
        ) -> str:
            """Search and summarize chat sessions.

            :param operation: Operation name.
            :param session_id: Optional explicit session id. Defaults to the active session when available.
            :param mode: Search mode for search_sessions: search, deep, or related. Defaults to search.
            :param query: User-provided search phrase for search and deep modes.
            :param limit: Positive integer result limit. Defaults to 5 for search_sessions and 50 for list_sessions.
            :param cursor: Opaque pagination cursor for list_sessions.
            :param summary_status: Optional list_sessions filter: summarized, any, current, pending, or stale.
            :param data: Summary field payload for upsert_session_summary.
            :param summarization_model: Model alias used by summarize_session.
            """
            try:
                deps = getattr(ctx, "deps", None)
                requested_session_id = str(session_id or "").strip() or None
                op = (operation or "").strip().lower()
                history_context = ChatHistoryContext.from_deps(deps)
                active_session_id = requested_session_id or history_context.session_id
                active_vault_name = history_context.vault_name
                store = SessionSummaryStore()

                logger.set_sinks(["validation"]).info(
                    "tool_invoked",
                    data={
                        "tool": "session_ops",
                        "operation": op,
                    },
                )

                resolved_limit = cls._parse_limit(
                    limit,
                    default=50 if op == "list_sessions" else 5,
                )
                if op == "list_sessions":
                    _require(active_vault_name, "vault_name is required")
                    result = _list_sessions(
                        vault_name=active_vault_name,
                        limit=_require_integer_limit(resolved_limit, operation="list_sessions"),
                        cursor=cursor,
                        summary_status=summary_status,
                    )
                elif op == "upsert_session_summary":
                    _require(active_vault_name, "vault_name is required")
                    _require(active_session_id, "session_id is required")
                    summary_data = _upsert_data(data)
                    summary_metadata = _with_current_history_metadata(
                        _summary_data_value(summary_data, "metadata"),
                        vault_name=active_vault_name,
                        session_id=active_session_id,
                    )
                    session_summary = store.upsert_session_summary(
                        vault_name=active_vault_name,
                        session_id=active_session_id,
                        title=_session_title(
                            vault_name=active_vault_name,
                            session_id=active_session_id,
                        ),
                        summary=_summary_data_value(summary_data, "summary"),
                        domain=_summary_data_value(summary_data, "domain"),
                        work_product=_summary_data_value(summary_data, "work_product"),
                        user_intent=_summary_data_value(summary_data, "user_intent"),
                        named_entities=_summary_data_value(summary_data, "named_entities"),
                        source_summary=_summary_data_value(summary_data, "source_summary"),
                        metadata=summary_metadata,
                    )
                    _maybe_add_artifacts(
                        store,
                        vault_name=active_vault_name,
                        session_id=active_session_id,
                        artifacts=summary_data.get("artifacts"),
                    )
                    indexed_fields = await _maybe_index_session_summary_fields(
                        store,
                        vault_name=active_vault_name,
                        session_id=active_session_id,
                    )
                    refreshed = store.get_session_summary(
                        vault_name=session_summary.vault_name,
                        session_id=session_summary.session_id,
                    )
                    result = {
                        "status": "ok",
                        "operation": op,
                        "indexed_fields": indexed_fields,
                        "session_summary": refreshed.to_dict() if refreshed else None,
                    }
                elif op == "summarize_session":
                    _require(active_vault_name, "vault_name is required")
                    _require(active_session_id, "session_id is required")
                    extraction = await _summarize_session(
                        vault_name=active_vault_name,
                        session_id=active_session_id,
                        summarization_model=summarization_model,
                    )
                    session_summary = store.upsert_session_summary(
                        vault_name=active_vault_name,
                        session_id=active_session_id,
                        title=extraction["title"],
                        summary=extraction["summary"],
                        domain=extraction["domain"],
                        work_product=extraction["work_product"],
                        user_intent=extraction["user_intent"],
                        named_entities=extraction["named_entities"],
                        source_summary=extraction["source_summary"],
                        metadata={
                            "source": "chat_session_extraction",
                            "extraction_policy": "summary_intent_classification_source_summary",
                            "summarization_model": summarization_model,
                            "message_count": extraction["message_count"],
                            "history_revision": extraction["history_revision"],
                            "tool_event_count": extraction["tool_event_count"],
                        },
                    )
                    artifact_count = _add_chat_mutation_artifacts(
                        store,
                        vault_name=active_vault_name,
                        session_id=active_session_id,
                    )
                    indexed_fields = await _maybe_index_session_summary_fields(
                        store,
                        vault_name=active_vault_name,
                        session_id=active_session_id,
                    )
                    refreshed = store.get_session_summary(
                        vault_name=session_summary.vault_name,
                        session_id=session_summary.session_id,
                    )
                    result = {
                        "status": "ok",
                        "operation": op,
                        "indexed_fields": indexed_fields,
                        "artifact_count": artifact_count,
                        "extraction": extraction,
                        "session_summary": refreshed.to_dict() if refreshed else None,
                    }
                elif op == "get_session_summary":
                    _require(active_vault_name, "vault_name is required")
                    _require(active_session_id, "session_id is required")
                    session_summary = store.get_session_summary(
                        vault_name=active_vault_name,
                        session_id=active_session_id,
                    )
                    result = {
                        "status": "found" if session_summary else "not_found",
                        "operation": op,
                        "vault_name": active_vault_name,
                        "session_id": active_session_id,
                        "session_summary": session_summary.to_dict()
                        if session_summary
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
                        "Unknown operation. Available: list_sessions, summarize_session, "
                        "upsert_session_summary, "
                        "get_session_summary, search_sessions"
                    )
                if hasattr(result, "to_dict"):
                    result = result.to_dict()
                return json.dumps(result, ensure_ascii=False, indent=2)
            except ModelRetry:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "session_ops failed",
                    data={
                        "operation": operation,
                        "session_id": session_id,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
                return f"Error performing '{operation}' operation: {exc}"

        return Tool(
            session_ops,
            name="session_ops",
            description="Search and summarize chat sessions.",
        )

    @classmethod
    def get_instructions(cls) -> str:
        """Get usage instructions for session lookup and summarization."""
        return """
Session summary field guidance:
- `summary`: compact plain-language summary of the session's durable outcome;
  target 500-800 characters and never exceed 1,000 characters.
- `domain`: semicolon-separated subject-area tags; use one to three compact
  noun phrases.
- `work_product`: concrete thing the user wanted produced or answered.
- `user_intent`: user's underlying goal or intent after clarification or drift;
  write one concise primary intent phrase and never exceed 140 characters.
- `named_entities`: only named people, organizations, and places.
- `source_summary`: concise description of source material or prior context
  identifiable from tool use. This is provenance returned with a summary, not an
  indexed retrieval field.

Use `list_sessions` for a compact browseable overview of chat sessions in the
current vault. It returns one page of lightweight rows ordered by most recent
activity, plus `total_count` and `next_cursor`. Use it when the user asks for an
overview, inventory, recent sessions, or sessions with missing/stale summaries.
By default, it lists only sessions with stored summaries. Rows include title,
timestamps, message count, summary status, domain, and user_intent. It does not
return full summaries or transcripts; call
`get_session_summary` for full details about one selected session.

Use `upsert_session_summary` only when you already have the field values to store
as the current session summary.
Pass those values in `data`; supported keys are `summary`, `domain`,
`work_product`, `user_intent`, `named_entities`, `source_summary`, `artifacts`,
and `metadata`.
It persists supplied values; it does not inspect the transcript or infer missing
fields. When updating an existing summary, omitted fields are preserved; pass
null or an empty string to explicitly clear a field.

Use `search_sessions` for caller-driven lookup across indexed chat-session
summaries. `search_sessions` has three modes:
- `search`: default. Searches a user-provided query across all session-summary
  fields.
- `deep`: searches a user-provided query across all session-summary fields and
  raw chat transcripts.
- `related`: compares an already-extracted current or specified session against
  prior sessions using the default compound related-work policy.

Mode selection:
- Use `search` for normal live-chat lookup when the current session does not
  yet have a stored summary.
- Use `deep` when the user asks for a broader or transcript-level search.
- Use `related` only when investigating an existing session that already has
  a stored summary and you want to find neighboring sessions.

For `search` and `deep`, write `query` as a plain natural-language phrase. Do
not use explicit boolean syntax such as uppercase AND/OR. Use a positive
integer `limit`. Search and deep modes require a query.

For manual writes, include only fields you intend to create, replace, or clear.
Leave unsupported or unchanged fields out of `data`.

Full documentation:
- `__virtual_docs__/tools/session_ops.md`
"""

    @staticmethod
    def _parse_limit(value: int | str, *, default: int) -> int | str:
        if isinstance(value, int):
            if value <= 0:
                raise ValueError("limit must be a positive integer or 'all'")
            return value
        normalized = str(value or "").strip().lower()
        if not normalized:
            return default
        if normalized == "all":
            return "all"
        if normalized.isdigit():
            parsed = int(normalized)
            if parsed <= 0:
                raise ValueError("limit must be a positive integer or 'all'")
            return parsed
        raise ValueError("limit must be a positive integer or 'all'")


class _SessionSummaryIntent(BaseModel):
    """First-pass session summarization."""

    summary: str = Field(default="", max_length=1000)
    user_intent: str = Field(default="", max_length=140)


class _SessionClassification(BaseModel):
    """Second-pass session classification."""

    named_entities: str = Field(default="")
    domain: str = Field(default="")
    work_product: str = Field(default="")


class _SessionSourceSummary(BaseModel):
    """Third-pass session source-summary extraction."""

    source_summary: str = Field(default="")


def _require(value: object, message: str) -> None:
    if value is None:
        raise ValueError(message)
    if isinstance(value, str) and not value.strip():
        raise ValueError(message)


def _session_title(*, vault_name: str, session_id: str) -> str | None:
    session = ChatStore().get_session(session_id=session_id, vault_name=vault_name)
    return session.title if session is not None else None


def _list_sessions(
    *,
    vault_name: str,
    limit: int,
    cursor: str,
    summary_status: str,
) -> dict[str, Any]:
    chat_store = ChatStore()
    summary_store = SessionSummaryStore()
    normalized_status = _normalize_summary_status_filter(summary_status)
    offset = _parse_cursor(cursor)
    rows: list[dict[str, Any]] = []
    for session in chat_store.list_sessions(vault_name):
        message_count = chat_store.get_message_count(
            session_id=session.session_id,
            vault_name=vault_name,
        )
        history_revision = chat_store.get_session_history_revision(
            session_id=session.session_id,
            vault_name=vault_name,
        )
        session_summary = summary_store.get_session_summary(
            vault_name=vault_name,
            session_id=session.session_id,
        )
        status = session_summary_status(
            session,
            session_summary,
            message_count=message_count,
            history_revision=history_revision,
        )
        if normalized_status == "summarized" and session_summary is None:
            continue
        if (
            normalized_status not in {"any", "summarized"}
            and status["summary_status"] != normalized_status
        ):
            continue
        rows.append(
            {
                "session_id": session.session_id,
                "title": session.title,
                "created_at": session.created_at,
                "last_activity_at": session.last_activity_at,
                "message_count": message_count,
                "history_revision": history_revision,
                "has_summary": session_summary is not None,
                "summary_status": status["summary_status"],
                "summary_updated_at": status["summary_updated_at"],
                "summary_message_count": status["summary_message_count"],
                "message_count_delta": status["message_count_delta"],
                "new_message_count": status["new_message_count"],
                "summary_history_revision": status["summary_history_revision"],
                "history_revision_delta": status["history_revision_delta"],
                "domain": session_summary.domain if session_summary else None,
                "user_intent": session_summary.user_intent if session_summary else None,
            }
        )

    page = rows[offset : offset + limit]
    next_offset = offset + len(page)
    return {
        "status": "ok",
        "operation": "list_sessions",
        "vault_name": vault_name,
        "summary_status": normalized_status,
        "total_count": len(rows),
        "returned_count": len(page),
        "cursor": str(offset) if offset else None,
        "next_cursor": str(next_offset) if next_offset < len(rows) else None,
        "sessions": page,
    }


def _normalize_summary_status_filter(value: str) -> str:
    normalized = str(value or "summarized").strip().lower()
    if normalized not in {"summarized", "any", "current", "pending", "stale"}:
        raise ModelRetry(
            "list_sessions summary_status must be one of: summarized, any, current, pending, stale."
        )
    return normalized


def _parse_cursor(value: str) -> int:
    normalized = str(value or "").strip()
    if not normalized:
        return 0
    if not normalized.isdigit():
        raise ModelRetry("list_sessions cursor must be the next_cursor value from a previous list_sessions result.")
    return int(normalized)


def _require_integer_limit(value: int | str, *, operation: str) -> int:
    if isinstance(value, int):
        if operation == "list_sessions" and value > 100:
            raise ModelRetry("list_sessions limit must be 100 or less.")
        return value
    raise ModelRetry(f"{operation} requires a positive integer limit.")


def _upsert_data(data: dict[str, Any] | None) -> dict[str, Any]:
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("data must be an object for upsert_session_summary")
    allowed_keys = {
        "summary",
        "domain",
        "work_product",
        "user_intent",
        "named_entities",
        "source_summary",
        "artifacts",
        "metadata",
    }
    unknown_keys = sorted(set(data) - allowed_keys)
    if unknown_keys:
        joined = ", ".join(unknown_keys)
        raise ValueError(f"Unsupported upsert_session_summary data keys: {joined}")

    parsed = dict(data)
    if parsed.get("metadata") is not None and not isinstance(parsed["metadata"], dict):
        raise ValueError("data.metadata must be an object")
    if parsed.get("artifacts") is not None and not isinstance(parsed["artifacts"], list):
        raise ValueError("data.artifacts must be a list")
    return parsed


def _summary_data_value(data: dict[str, Any], key: str) -> Any:
    if key not in data:
        return SESSION_SUMMARY_FIELD_UNSET
    return data[key]


def _with_current_history_metadata(
    metadata: Any,
    *,
    vault_name: str,
    session_id: str,
) -> dict[str, Any]:
    if isinstance(metadata, dict):
        base = dict(metadata)
    else:
        existing = SessionSummaryStore().get_session_summary(
            vault_name=vault_name,
            session_id=session_id,
        )
        base = dict(existing.metadata) if existing is not None else {}
    chat_store = ChatStore()
    base["message_count"] = chat_store.get_message_count(
        session_id=session_id,
        vault_name=vault_name,
    )
    base["history_revision"] = chat_store.get_session_history_revision(
        session_id=session_id,
        vault_name=vault_name,
    )
    return base


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


def _related_match_to_dict(match: Any) -> dict[str, Any]:
    payload = match.to_dict()
    if "session_summary" in payload:
        payload["session_summary"] = payload.pop("session_summary")
    return payload


async def _search_sessions(
    *,
    store: SessionSummaryStore,
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
            "matches": [_related_match_to_dict(match) for match in matches],
        }

    _require(query, "query is required for search and deep modes")
    memory_matches = await _search_session_summary_fields(
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


async def _search_session_summary_fields(
    *,
    store: SessionSummaryStore,
    vault_name: str,
    query: str,
    limit: int,
) -> dict[str, dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    lexical_matches = store.search_session_summaries_fts(
        vault_name=vault_name,
        query=query,
        limit=max(limit * 4, limit),
    )
    for match in lexical_matches:
        session_summary = match.session_summary
        weighted_score = round(float(match.score or 0.0) * SESSION_LEXICAL_WEIGHT, 6)
        candidate = candidates.setdefault(
            session_summary.session_id,
            {
                "session_id": session_summary.session_id,
                "vault_name": session_summary.vault_name,
                "field_scores": {},
                "session_summary": session_summary.to_dict(),
                "evidence": [],
            },
        )
        candidate["field_scores"]["session_summary_fts"] = max(
            float(candidate["field_scores"].get("session_summary_fts", 0.0)),
            weighted_score,
        )
        candidate["evidence"].append(
            {
                "source": "session_summary",
                "match_type": "lexical",
                "score": match.score,
                "weighted_score": weighted_score,
                "rank": match.rank,
                "matched_value": None,
            }
        )

    for current_field in VECTOR_FIELD_TYPES:
        matches = await store.search_session_summaries_by_field(
            vault_name=vault_name,
            field_type=current_field,
            value=query,
            vector_service=VectorService(),
            limit=max(limit * 3, limit),
            min_score=SUMMARY_VECTOR_MIN_SCORE,
            include_direct=False,
        )
        field_weight = SESSION_SEARCH_FIELD_WEIGHTS.get(current_field, 0.5)
        for match in matches:
            session_summary = match.session_summary
            normalized_score = _normalize_vector_score(float(match.score or 0.0))
            weighted_score = round(normalized_score * field_weight, 6)
            candidate = candidates.setdefault(
                session_summary.session_id,
                {
                    "session_id": session_summary.session_id,
                    "vault_name": session_summary.vault_name,
                    "field_scores": {},
                    "session_summary": session_summary.to_dict(),
                    "evidence": [],
                },
            )
            candidate["field_scores"][current_field] = max(
                float(candidate["field_scores"].get(current_field, 0.0)),
                weighted_score,
            )
            candidate["evidence"].append(
                {
                    "source": "session_summary",
                    "field_type": current_field,
                    "match_type": match.match_type,
                    "score": match.score,
                    "normalized_score": normalized_score,
                    "weighted_score": weighted_score,
                    "matched_value": _preview_text(session_summary.field_value(current_field)),
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
    store: SessionSummaryStore,
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
        session_summary = store.get_session_summary(
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
                "session_summary": session_summary.to_dict() if session_summary else None,
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
        if session_summary is not None and candidate.get("session_summary") is None:
            candidate["session_summary"] = session_summary.to_dict()
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
    score = min(abs(rank) / 10.0, 1.0)
    if rank != 0.0:
        score = max(score, 0.000001)
    return round(score, 6)


def _normalize_vector_score(score: float) -> float:
    if score <= SUMMARY_VECTOR_MIN_SCORE:
        return 0.0
    return round((score - SUMMARY_VECTOR_MIN_SCORE) / (1.0 - SUMMARY_VECTOR_MIN_SCORE), 6)


async def _summarize_session(
    *,
    vault_name: str,
    session_id: str,
    summarization_model: str,
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
    tool_events = ChatHistoryService(chat_store=chat_store).get_conversation_tool_events(
        context=ChatHistoryContext(session_id=session_id, vault_name=vault_name),
        scope="session",
        session_id=session_id,
        limit="all",
    )
    if not history.items:
        raise ValueError(f"Chat session has no persisted messages: {session_id}")
    summary_agent = await create_agent(
        model=build_model_instance(summarization_model),
        output_type=_SessionSummaryIntent,
    )
    classification_agent = await create_agent(
        model=build_model_instance(summarization_model),
        output_type=_SessionClassification,
    )
    source_agent = await create_agent(
        model=build_model_instance(summarization_model),
        output_type=_SessionSourceSummary,
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
    tool_event_log = _build_tool_event_log(tool_events.items)
    if tool_event_log:
        source_summary = await generate_response(
            source_agent,
            _build_source_summary_prompt(
                session=session,
                summary_intent=summary_intent_data,
                tool_event_log=tool_event_log,
            ),
        )
        source_summary_data = source_summary.model_dump()
    else:
        source_summary_data = {"source_summary": ""}
    return {
        "session_id": session.session_id,
        "vault_name": session.vault_name,
        "title": session.title,
        "summary": summary_intent_data["summary"],
        "user_intent": summary_intent_data["user_intent"],
        "domain": classification_data["domain"],
        "work_product": classification_data["work_product"],
        "named_entities": classification_data["named_entities"],
        "source_summary": source_summary_data["source_summary"],
        "message_count": history.item_count,
        "history_revision": chat_store.get_session_history_revision(
            session_id=session_id,
            vault_name=vault_name,
        ),
        "tool_event_count": tool_events.item_count,
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
    return SESSION_SUMMARY_INTENT_PROMPT.format(
        session_id=session.session_id,
        vault_name=session.vault_name,
        title=title,
        created_at=session.created_at,
        last_activity_at=session.last_activity_at,
        transcript=transcript,
    )


def _build_second_pass_prompt(
    *,
    session: StoredChatSession,
    summary_intent: dict[str, str],
) -> str:
    title = session.title or ""
    return SESSION_SUMMARY_CLASSIFICATION_PROMPT.format(
        session_id=session.session_id,
        title=title,
        summary=summary_intent["summary"],
        user_intent=summary_intent["user_intent"],
    )


def _build_source_summary_prompt(
    *,
    session: StoredChatSession,
    summary_intent: dict[str, str],
    tool_event_log: str,
) -> str:
    title = session.title or ""
    return SESSION_SUMMARY_SOURCE_SUMMARY_PROMPT.format(
        session_id=session.session_id,
        title=title,
        summary=summary_intent["summary"],
        user_intent=summary_intent["user_intent"],
        tool_event_log=tool_event_log,
    )


def _build_tool_event_log(events: tuple[ConversationToolEventItem, ...]) -> str:
    """Build a flat extraction-only log from structured chat tool events."""
    args_by_call_id: dict[str, dict[str, Any] | None] = {}
    rows: list[str] = []
    result_index = 0
    for event in events:
        if event.event_type == "call":
            args_by_call_id[event.tool_call_id] = event.args
            continue
        if event.event_type != "result":
            continue
        args = args_by_call_id.get(event.tool_call_id)
        if _is_virtual_docs_file_call(event, args):
            continue
        if _is_failed_tool_result(event):
            continue
        result_index += 1
        args_text = json.dumps(args or {}, ensure_ascii=False, sort_keys=True)
        result_text = _preview_text(event.result_text, limit=800) or ""
        rows.append(
            "\n".join(
                (
                    f"{result_index}. Tool: {event.tool_name}",
                    f"   args: {args_text}",
                    f"   result: {result_text}",
                )
            )
        )
    return "\n\n".join(rows)


def _is_failed_tool_result(event: ConversationToolEventItem) -> bool:
    metadata = event.result_metadata or {}
    status = str(metadata.get("status") or metadata.get("state") or "").strip().lower()
    if status in {"error", "failed", "failure"}:
        return True
    result_text = str(event.result_text or "").strip().lower()
    return result_text.startswith(("error:", "error performing "))


def _is_virtual_docs_file_call(
    event: ConversationToolEventItem,
    args: dict[str, Any] | None,
) -> bool:
    if event.tool_name != "file_ops_safe" or not args:
        return False
    paths = _extract_arg_paths(args)
    return bool(paths) and all(path.startswith("__virtual_docs__/") for path in paths)


def _extract_arg_paths(value: Any) -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in {"path", "source_path", "target_path", "from_path", "to_path"}:
                path = str(nested or "").strip()
                if path:
                    paths.append(path)
                continue
            if key in {"paths", "files"} and isinstance(nested, list):
                paths.extend(str(item or "").strip() for item in nested if str(item or "").strip())
    return paths


async def _maybe_index_session_summary_fields(
    store: SessionSummaryStore,
    *,
    vault_name: str,
    session_id: str,
) -> int:
    try:
        return await store.index_session_summary_fields(
            vault_name=vault_name,
            session_id=session_id,
            vector_service=VectorService(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "session_summary_field_indexing_skipped",
            data={
                "vault_name": vault_name,
                "session_id": session_id,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        return 0


def _maybe_add_artifacts(
    store: SessionSummaryStore,
    *,
    vault_name: str,
    session_id: str,
    artifacts: list[dict[str, Any]] | None,
) -> None:
    parsed: list[SessionSummaryArtifact] = []
    for raw in artifacts or []:
        path = str(raw.get("path") or "").strip()
        _require(path, "path is required for each artifact")
        parsed.append(
            SessionSummaryArtifact(
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
    store: SessionSummaryStore,
    *,
    vault_name: str,
    session_id: str,
) -> int:
    """Attach vault files mutated by this chat session to its session summary row."""
    try:
        mutations = VaultStateService().list_chat_session_mutations(
            vault_name=vault_name,
            session_id=session_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "session_summary_artifact_population_skipped",
            data={
                "vault_name": vault_name,
                "session_id": session_id,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        return 0

    artifacts_by_key: dict[tuple[str, str], SessionSummaryArtifact] = {}
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
        artifacts_by_key[key] = SessionSummaryArtifact(
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
