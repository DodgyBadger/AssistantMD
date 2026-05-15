"""Session memory operations tool."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import RunContext
from pydantic_ai.tools import Tool

from core.chat.chat_store import ChatStore, StoredChatMessage, StoredChatSession
from core.llm.agents import create_agent, generate_response
from core.llm.model_factory import build_model_instance
from core.logger import UnifiedLogger
from core.memory import MemoryContext
from core.memory.session_memory import (
    RELATED_SESSION_AUTOMATIC_THRESHOLD,
    RELATED_SESSION_POSSIBLE_THRESHOLD,
    RELATED_SESSION_FIELD_WEIGHTS,
    SessionMemoryArtifact,
    SessionMemoryStore,
)
from core.vector import VectorService

from .base import BaseTool


logger = UnifiedLogger(tag="memory-ops-tool")


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
            limit: int | str = "all",
            title: str | None = None,
            summary: str | None = None,
            domain: str | None = None,
            work_product: str | None = None,
            user_intent: str | None = None,
            named_entities: str | None = None,
            field_type: str = "",
            value: str = "",
            extraction_model: str = "gpt-mini",
            artifacts: list[dict[str, Any]] | None = None,
            metadata: dict[str, Any] | None = None,
        ) -> str:
            """Manage memory extracted from chat sessions.

            :param operation: Operation name.
            :param session_id: Optional explicit session id. Defaults to the active session when available.
            :param limit: Positive integer or "all".
            :param title: Optional human-readable session label.
            :param summary: Short plain-language summary of the chat session.
            :param domain: Subject area or knowledge area.
            :param work_product: Concrete thing the user wanted produced or answered.
            :param user_intent: User's underlying goal or intent.
            :param named_entities: Named people, organizations, and places.
            :param field_type: Field type for search operations.
            :param value: Field value for search operations.
            :param extraction_model: Model alias used by extract_session_memory.
            :param artifacts: Optional list of artifact objects.
            :param metadata: Optional object metadata for upsert operations.
            """
            try:
                deps = getattr(ctx, "deps", None)
                requested_session_id = str(session_id or "").strip() or None
                op = (operation or "").strip().lower()
                memory_context = MemoryContext.from_deps(deps)
                active_session_id = requested_session_id or memory_context.session_id
                active_vault_name = memory_context.vault_name
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
                    session_memory = store.upsert_session_memory(
                        vault_name=active_vault_name,
                        session_id=active_session_id,
                        title=title,
                        summary=summary,
                        domain=domain,
                        work_product=work_product,
                        user_intent=user_intent,
                        named_entities=named_entities,
                        metadata=metadata,
                    )
                    _maybe_add_artifacts(
                        store,
                        vault_name=active_vault_name,
                        session_id=active_session_id,
                        artifacts=artifacts,
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
                        title=title or extraction["title"],
                        summary=extraction["summary"],
                        domain=extraction["domain"],
                        work_product=extraction["work_product"],
                        user_intent=extraction["user_intent"],
                        named_entities=extraction["named_entities"],
                        metadata={
                            **(metadata or {}),
                            "source": "chat_session_extraction",
                            "extraction_policy": "two_step_summary_intent_then_classification",
                            "extraction_model": extraction_model,
                            "message_count": extraction["message_count"],
                        },
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
                    resolved_search_limit = resolved_limit if isinstance(resolved_limit, int) else 20
                    if field_type and value:
                        matches = await store.search_session_memories_by_field(
                            vault_name=active_vault_name,
                            field_type=field_type,
                            value=value,
                            vector_service=VectorService(),
                            limit=resolved_search_limit,
                        )
                        result = {
                            "status": "ok",
                            "operation": op,
                            "query": {
                                "field_type": field_type,
                                "value": value,
                            },
                            "matches": [match.to_dict() for match in matches],
                            "session_memories": [
                                match.session_memory.to_dict() for match in matches
                            ],
                        }
                    else:
                        session_memories = store.search_session_memories(
                            vault_name=active_vault_name,
                            limit=resolved_search_limit,
                        )
                        result = {
                            "status": "ok",
                            "operation": op,
                            "session_memories": [
                                session_memory.to_dict()
                                for session_memory in session_memories
                            ],
                        }
                elif op == "find_related_sessions":
                    _require(active_vault_name, "vault_name is required")
                    resolved_search_limit = resolved_limit if isinstance(resolved_limit, int) else 5
                    matches = await store.find_related_sessions(
                        vault_name=active_vault_name,
                        session_id=active_session_id,
                        vector_service=VectorService(),
                        limit=resolved_search_limit,
                    )
                    result = {
                        "status": "ok",
                        "operation": op,
                        "query": {
                            "vault_name": active_vault_name,
                            "session_id": active_session_id,
                            "policy": {
                                "weights": RELATED_SESSION_FIELD_WEIGHTS,
                                "automatic_threshold": RELATED_SESSION_AUTOMATIC_THRESHOLD,
                                "possible_threshold": RELATED_SESSION_POSSIBLE_THRESHOLD,
                            },
                        },
                        "matches": [match.to_dict() for match in matches],
                        "session_memories": [
                            match.session_memory.to_dict() for match in matches
                        ],
                    }
                else:
                    return (
                        "Unknown operation. Available: extract_session_memory, "
                        "upsert_session_memory, "
                        "get_session_memory, search_sessions, find_related_sessions"
                    )
                if hasattr(result, "to_dict"):
                    result = result.to_dict()
                return json.dumps(result, ensure_ascii=False, indent=2)
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

Use `search_sessions` for caller-driven lookup across indexed chat-session
memory. Use `find_related_sessions` with only `session_id` and `limit` when you
want the current or specified session compared against prior sessions using the
default compound related-work policy.

Update only fields supported by current context. Leave unknown fields empty.

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
    messages = chat_store.get_stored_messages(
        session_id=session_id,
        vault_name=vault_name,
    )
    if not messages:
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
        _build_first_pass_prompt(session=session, messages=messages),
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
        "message_count": len(messages),
    }


def _build_first_pass_prompt(
    *,
    session: StoredChatSession,
    messages: list[StoredChatMessage],
) -> str:
    transcript = "\n\n".join(
        f"{message.role.upper()} [{message.sequence_index}]:\n{message.content_text}"
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
