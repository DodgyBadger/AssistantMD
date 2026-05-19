"""Definition and execution for the retrieve_sessions(...) Monty helper."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.authoring.contracts import (
    AuthoringCapabilityCall,
    AuthoringCapabilityDefinition,
    AuthoringExecutionContext,
    RetrievedItem,
    RetrievedSessionsResult,
)
from core.authoring.helpers.common import build_capability
from core.chat.chat_store import ChatStore, StoredChatSession
from core.logger import UnifiedLogger
from core.memory.session_memory import SessionMemoryStore
from core.settings import get_stale_memory_min_new_messages


logger = UnifiedLogger(tag="authoring-host")

PENDING_OR_STALE_MEMORY_SELECTION = "pending_or_stale_memory"
STALE_MEMORY_GRACE_MINUTES = 30


def build_definition() -> AuthoringCapabilityDefinition:
    return build_capability(
        name="retrieve_sessions",
        doc="Retrieve chat-session metadata for workflow and context scripts.",
        contract=_contract(),
        handler=execute,
    )


async def execute(
    call: AuthoringCapabilityCall,
    context: AuthoringExecutionContext,
) -> RetrievedSessionsResult:
    selection, limit = _parse_call(call)
    vault_name = _vault_name_from_workflow_id(context.workflow_id)
    active_session_id = getattr(context.host, "chat_session_id", None)
    logger.add_sink("validation").info(
        "authoring_retrieve_sessions_started",
        data={
            "workflow_id": context.workflow_id,
            "selection": selection,
            "vault_name": vault_name,
            "limit": limit,
        },
    )

    chat_store = ChatStore()
    memory_store = SessionMemoryStore()
    stale_memory_min_new_messages = get_stale_memory_min_new_messages()
    sessions = chat_store.list_sessions(vault_name)
    items: list[RetrievedItem] = []
    for session in sessions:
        if active_session_id and session.session_id == active_session_id:
            continue
        message_count = chat_store.get_message_count(
            session_id=session.session_id,
            vault_name=vault_name,
        )
        if selection == PENDING_OR_STALE_MEMORY_SELECTION:
            memory = memory_store.get_session_memory(
                vault_name=vault_name,
                session_id=session.session_id,
            )
            memory_status = _memory_status(
                session,
                memory,
                message_count=message_count,
                stale_memory_min_new_messages=stale_memory_min_new_messages,
            )
            if memory_status["memory_status"] == "current":
                continue
        else:  # pragma: no cover - guarded by _parse_call
            raise ValueError(f"Unsupported retrieve_sessions selection: {selection}")
        items.append(
            _session_item(
                session,
                message_count=message_count,
                has_memory=memory is not None,
                memory_status=memory_status,
            )
        )

    items.sort(key=lambda item: str(item.metadata.get("last_activity_at") or ""))
    limited_items = tuple(items if limit == "all" else items[:limit])
    result = RetrievedSessionsResult(
        selection=selection,
        status="ok",
        item_count=len(limited_items),
        items=limited_items,
        metadata={
            "vault_name": vault_name,
            "limit": limit,
        },
    )
    logger.add_sink("validation").info(
        "authoring_retrieve_sessions_completed",
        data={
            "workflow_id": context.workflow_id,
            "selection": result.selection,
            "vault_name": vault_name,
            "item_count": result.item_count,
        },
    )
    return result


def _parse_call(call: AuthoringCapabilityCall) -> tuple[str, int | str]:
    if call.args:
        raise ValueError("retrieve_sessions only supports keyword arguments")
    selection = str(
        call.kwargs.get("selection") or PENDING_OR_STALE_MEMORY_SELECTION
    ).strip().lower()
    if selection != PENDING_OR_STALE_MEMORY_SELECTION:
        raise ValueError("retrieve_sessions selection must be 'pending_or_stale_memory'")
    return selection, _parse_limit(call.kwargs.get("limit", "all"))


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


def _vault_name_from_workflow_id(workflow_id: str) -> str:
    if "/" not in workflow_id:
        raise ValueError(f"Invalid workflow_id format. Expected 'vault/name', got: {workflow_id}")
    vault_name, _ = workflow_id.split("/", 1)
    if not vault_name:
        raise ValueError(f"Invalid workflow_id format. Expected 'vault/name', got: {workflow_id}")
    return vault_name


def _session_item(
    session: StoredChatSession,
    *,
    message_count: int,
    has_memory: bool,
    memory_status: dict[str, object],
) -> RetrievedItem:
    title = session.title or ""
    content = title or session.session_id
    metadata = {
        "session_id": session.session_id,
        "vault_name": session.vault_name,
        "title": title,
        "created_at": session.created_at,
        "last_activity_at": session.last_activity_at,
        "message_count": message_count,
        "has_memory": has_memory,
        **memory_status,
    }
    return RetrievedItem(
        ref=f"chat_session:{session.session_id}",
        content=content,
        exists=True,
        metadata=metadata,
    )


def _memory_status(
    session: StoredChatSession,
    memory: object | None,
    *,
    message_count: int,
    stale_memory_min_new_messages: int,
) -> dict[str, object]:
    if memory is None:
        return {
            "memory_status": "pending",
            "memory_updated_at": None,
            "memory_message_count": None,
            "new_message_count": message_count,
        }

    memory_updated_at = str(getattr(memory, "updated_at", "") or "")
    memory_message_count = _memory_message_count(getattr(memory, "metadata", {}) or {})
    new_message_count = (
        max(message_count - memory_message_count, 0)
        if memory_message_count is not None
        else None
    )
    session_last_activity = _parse_timestamp(session.last_activity_at)
    memory_updated = _parse_timestamp(memory_updated_at)
    if session_last_activity is None or memory_updated is None:
        stale = new_message_count is None or new_message_count >= stale_memory_min_new_messages
    else:
        grace_cutoff = memory_updated + timedelta(minutes=STALE_MEMORY_GRACE_MINUTES)
        stale = (
            session_last_activity > grace_cutoff
            and (
                new_message_count is None
                or new_message_count >= stale_memory_min_new_messages
            )
        )

    return {
        "memory_status": "stale" if stale else "current",
        "memory_updated_at": memory_updated_at,
        "memory_message_count": memory_message_count,
        "new_message_count": new_message_count,
        "stale_memory_grace_minutes": STALE_MEMORY_GRACE_MINUTES,
        "stale_memory_min_new_messages": stale_memory_min_new_messages,
    }


def _memory_message_count(metadata: dict[str, object]) -> int | None:
    raw = metadata.get("message_count")
    try:
        count = int(raw)
    except (TypeError, ValueError):
        return None
    return count if count >= 0 else None


def _parse_timestamp(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    if "T" not in normalized and " " in normalized:
        normalized = normalized.replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _contract() -> dict[str, object]:
    return {
        "signature": "retrieve_sessions(*, selection: str = 'pending_or_stale_memory', limit: int | str = 'all')",
        "summary": (
            "Retrieve chat-session metadata for the current vault. "
            "The 'pending_or_stale_memory' selection returns sessions without "
            "memory or with memory older than recent session activity. "
            "Stale selection respects the stale_memory_min_new_messages setting."
        ),
        "arguments": {
            "selection": {
                "type": "string",
                "required": False,
                "description": "Selection to return. Currently only 'pending_or_stale_memory' is supported.",
            },
            "limit": {
                "type": "int|string",
                "required": False,
                "description": "Positive integer or 'all'.",
            },
        },
        "return_shape": {
            "selection": "Resolved selection.",
            "status": "Result status.",
            "item_count": "Number of returned session items.",
            "items": (
                "Session metadata items. Each item has ref, content, exists, and metadata "
                "including session_id, vault_name, title, created_at, last_activity_at, "
                "message_count, has_memory, memory_status, memory_updated_at, "
                "memory_message_count, new_message_count, stale_memory_grace_minutes, "
                "and stale_memory_min_new_messages."
            ),
            "metadata": "Retrieval metadata.",
        },
        "examples": [
            {
                "code": (
                    "sessions = await retrieve_sessions(selection='pending_or_stale_memory', limit=100)\n"
                    "for item in sessions.items:\n"
                    "    await memory_ops(operation='extract_session_memory', "
                    "session_id=item.metadata['session_id'])"
                ),
                "description": "Find sessions with missing or stale memory and extract them in a workflow.",
            }
        ],
    }
