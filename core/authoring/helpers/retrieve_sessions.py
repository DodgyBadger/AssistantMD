"""Definition and execution for the retrieve_sessions(...) Monty helper."""

from __future__ import annotations

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
from core.memory.session_summary import SessionSummaryStore
from core.memory.session_summary_status import session_summary_status


logger = UnifiedLogger(tag="authoring-host")

PENDING_OR_STALE_SUMMARY_SELECTION = "pending_or_stale_summary"


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
    summary_store = SessionSummaryStore()
    sessions = chat_store.list_sessions(vault_name)
    items: list[RetrievedItem] = []
    for session in sessions:
        if active_session_id and session.session_id == active_session_id:
            continue
        message_count = chat_store.get_message_count(
            session_id=session.session_id,
            vault_name=vault_name,
        )
        if selection == PENDING_OR_STALE_SUMMARY_SELECTION:
            session_summary = summary_store.get_session_summary(
                vault_name=vault_name,
                session_id=session.session_id,
            )
            summary_status = session_summary_status(
                session,
                session_summary,
                message_count=message_count,
            )
            if summary_status["summary_status"] == "current":
                continue
        else:  # pragma: no cover - guarded by _parse_call
            raise ValueError(f"Unsupported retrieve_sessions selection: {selection}")
        items.append(
            _session_item(
                session,
                message_count=message_count,
                has_summary=session_summary is not None,
                summary_status=summary_status,
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
        call.kwargs.get("selection") or PENDING_OR_STALE_SUMMARY_SELECTION
    ).strip().lower()
    if selection != PENDING_OR_STALE_SUMMARY_SELECTION:
        raise ValueError("retrieve_sessions selection must be 'pending_or_stale_summary'")
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
    has_summary: bool,
    summary_status: dict[str, object],
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
        "has_summary": has_summary,
        **summary_status,
    }
    return RetrievedItem(
        ref=f"chat_session:{session.session_id}",
        content=content,
        exists=True,
        metadata=metadata,
    )


def _contract() -> dict[str, object]:
    return {
        "signature": "retrieve_sessions(*, selection: str = 'pending_or_stale_summary', limit: int | str = 'all')",
        "summary": (
            "Retrieve chat-session metadata for the current vault. "
            "The 'pending_or_stale_summary' selection returns sessions without "
            "a session summary or with a summary message count that differs from "
            "the current persisted session message count."
        ),
        "arguments": {
            "selection": {
                "type": "string",
                "required": False,
                "description": "Selection to return. Currently only 'pending_or_stale_summary' is supported.",
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
                "message_count, has_summary, summary_status, summary_updated_at, "
                "summary_message_count, message_count_delta, and new_message_count."
            ),
            "metadata": "Retrieval metadata.",
        },
        "examples": [
            {
                "code": (
                    "sessions = await retrieve_sessions(selection='pending_or_stale_summary', limit=100)\n"
                    "for item in sessions.items:\n"
                    "    await session_ops(operation='summarize_session', "
                    "session_id=item.metadata['session_id'])"
                ),
                "description": "Find sessions with missing or stale summaries and summarize them in a workflow.",
            }
        ],
    }
