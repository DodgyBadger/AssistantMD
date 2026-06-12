"""Definition and execution for the retrieve_history(...) Monty helper."""

from __future__ import annotations

from typing import Any

from core.authoring.contracts import (
    AuthoringCapabilityCall,
    AuthoringCapabilityDefinition,
    AuthoringExecutionContext,
    HistoryMessage,
    RetrievedHistoryResult,
    ToolExchange,
    ToolExchangeBatch,
)
from core.authoring.helpers.common import build_capability
from core.chat.tool_history import analyze_tool_history_payloads
from core.chat.history_service import ChatHistoryContext, ChatHistoryService
from core.logger import UnifiedLogger


_CHAT_HISTORY_SERVICE = ChatHistoryService()
logger = UnifiedLogger(tag="authoring-host")


def build_definition() -> AuthoringCapabilityDefinition:
    return build_capability(
        name="retrieve_history",
        doc=(
            "Retrieve structured conversation history directly from the shared chat-history broker. "
            "Tool exchanges are returned as atomic units."
        ),
        contract=_contract(),
        handler=execute,
    )


async def execute(
    call: AuthoringCapabilityCall,
    context: AuthoringExecutionContext,
) -> RetrievedHistoryResult:
    host = context.host
    scope, session_id, limit, message_filter = _parse_call(call)
    logger.set_sinks(["validation"]).info(
        "authoring_retrieve_history_started",
        data={
            "workflow_id": context.workflow_id,
            "scope": scope,
            "session_id": session_id or getattr(host, "chat_session_id", None) or getattr(host, "session_key", None),
            "limit": limit,
            "message_filter": message_filter,
        },
    )
    host_message_history = getattr(host, "message_history", None)
    workflow_id = str(context.workflow_id)
    prefer_host_history = (
        host_message_history is not None
        and bool(getattr(host, "prefer_message_history", False))
    )
    result = _CHAT_HISTORY_SERVICE.get_conversation_history(
        context=ChatHistoryContext(
            message_history=tuple(host_message_history or ()),
            session_id=getattr(host, "chat_session_id", None) or getattr(host, "session_key", None),
            vault_name=workflow_id.split("/", 1)[0] if "/" in workflow_id else None,
            prefer_message_history=prefer_host_history,
        ),
        scope=scope,
        session_id=session_id,
        limit=limit,
        message_filter=message_filter,
    )
    integrity = analyze_tool_history_payloads(
        tuple(
            item.message
            for item in result.items
            if isinstance(getattr(item, "message", None), dict)
        )
    )
    items = tuple(_build_safe_history_items(result.items))
    metadata = dict(result.metadata)
    metadata["tool_history_integrity"] = integrity.to_dict()
    response = RetrievedHistoryResult(
        source=result.source,
        scope=result.scope,
        session_id=result.session_id,
        item_count=len(items),
        items=items,
        metadata=metadata,
    )
    if not integrity.ok:
        logger.set_sinks(["validation"]).warning(
            "authoring_retrieve_history_tool_integrity_issue",
            data={
                "workflow_id": context.workflow_id,
                "scope": response.scope,
                "session_id": response.session_id,
                **integrity.to_dict(),
            },
        )
    logger.set_sinks(["validation"]).info(
        "authoring_retrieve_history_completed",
        data={
            "workflow_id": context.workflow_id,
            "scope": response.scope,
            "session_id": response.session_id,
            "item_count": response.item_count,
            "source": response.source,
            "message_filter": response.metadata.get("message_filter"),
            "tool_history_integrity_status": integrity.status,
            "tool_history_issue_count": len(integrity.issues),
            "multi_call_batch_count": integrity.multi_call_batch_count,
            "multi_return_batch_count": integrity.multi_return_batch_count,
        },
    )
    return response


def _parse_call(call: AuthoringCapabilityCall) -> tuple[str, str | None, int | str, str]:
    if call.args:
        raise ValueError("retrieve_history only supports keyword arguments")
    scope = str(call.kwargs.get("scope") or "session").strip() or "session"
    raw_session_id = call.kwargs.get("session_id")
    session_id = str(raw_session_id).strip() if raw_session_id not in (None, "") else None
    limit = call.kwargs.get("limit", "all")
    parsed_limit = _parse_limit(limit)
    message_filter = str(call.kwargs.get("message_filter") or "all").strip() or "all"
    return scope, session_id, parsed_limit, message_filter


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


def _build_safe_history_items(items: tuple[Any, ...]) -> list[HistoryMessage | ToolExchange | ToolExchangeBatch]:
    safe_items: list[HistoryMessage | ToolExchange | ToolExchangeBatch] = []
    index = 0
    item_list = list(items)
    while index < len(item_list):
        current = item_list[index]
        current_message = current.message if isinstance(getattr(current, "message", None), dict) else None
        if current_message is not None:
            exchange, consumed = _consume_tool_exchange(item_list, index)
            if exchange is not None:
                safe_items.append(exchange)
                index += consumed
                continue
        safe_items.append(
            HistoryMessage(
                role=str(getattr(current, "role", "") or ""),
                content=str(getattr(current, "content", "") or ""),
                message=current_message,
                metadata=dict(getattr(current, "metadata", {}) or {}),
            )
        )
        index += 1
    return safe_items


def _consume_tool_exchange(
    items: list[Any],
    start_index: int,
) -> tuple[ToolExchange | ToolExchangeBatch | None, int]:
    first = items[start_index]
    first_message = first.message if isinstance(getattr(first, "message", None), dict) else None
    if first_message is None or str(getattr(first, "message_type", "") or "") != "ModelResponse":
        return None, 1

    first_parts = list(first_message.get("parts") or ())
    tool_call_parts = [part for part in first_parts if part.get("part_kind") == "tool-call"]
    if not tool_call_parts:
        return None, 1

    tool_calls_by_id = {
        str(part.get("tool_call_id") or "").strip(): part
        for part in tool_call_parts
        if str(part.get("tool_call_id") or "").strip()
    }
    if len(tool_calls_by_id) != len(tool_call_parts):
        return None, 1

    if start_index + 1 >= len(items):
        return None, 1
    second = items[start_index + 1]
    second_message = second.message if isinstance(getattr(second, "message", None), dict) else None
    if second_message is None or str(getattr(second, "message_type", "") or "") != "ModelRequest":
        return None, 1

    second_parts = list(second_message.get("parts") or ())
    tool_return_parts = [part for part in second_parts if part.get("part_kind") == "tool-return"]
    if not tool_return_parts:
        return None, 1

    tool_returns_by_id = {
        str(part.get("tool_call_id") or "").strip(): part
        for part in tool_return_parts
        if str(part.get("tool_call_id") or "").strip()
    }
    if set(tool_returns_by_id) != set(tool_calls_by_id):
        return None, 1

    metadata = dict(getattr(first, "metadata", {}) or {})
    metadata.update(dict(getattr(second, "metadata", {}) or {}))
    exchanges = tuple(
        ToolExchange(
            tool_call_id=tool_call_id,
            tool_name=str(tool_call_part.get("tool_name") or "").strip(),
            request_message=dict(first_message),
            response_message=dict(second_message),
            call_arguments=_tool_call_arguments(tool_call_part),
            result_text=_tool_return_text(tool_returns_by_id[tool_call_id]),
            metadata=metadata,
        )
        for tool_call_id, tool_call_part in tool_calls_by_id.items()
    )
    if len(exchanges) == 1:
        return exchanges[0], 2
    return (
        ToolExchangeBatch(
            request_message=dict(first_message),
            response_message=dict(second_message),
            exchanges=exchanges,
            metadata=metadata | {"tool_exchange_count": len(exchanges)},
        ),
        2,
    )


def _tool_call_arguments(tool_call_part: dict[str, Any]) -> dict[str, Any] | None:
    call_arguments = tool_call_part.get("args")
    return call_arguments if isinstance(call_arguments, dict) else None


def _tool_return_text(tool_return_part: dict[str, Any]) -> str | None:
    result_text = tool_return_part.get("content")
    return None if result_text is None else str(result_text)


def _contract() -> dict[str, object]:
    return {
        "signature": (
            "retrieve_history(*, scope: str = 'session', session_id: str | None = None, "
            "limit: int | str = 'all', message_filter: str = 'all')"
        ),
        "summary": (
            "Retrieve conversation history directly from the shared chat-history broker. "
            "Items are safe units: user message, assistant message, or one atomic tool exchange."
        ),
        "arguments": {
            "scope": {
                "type": "string",
                "required": False,
                "description": "History scope. Currently only 'session' is supported.",
            },
            "session_id": {
                "type": "string",
                "required": False,
                "description": "Optional explicit session id. Defaults to the active session.",
            },
            "limit": {
                "type": "int|string",
                "required": False,
                "description": "Positive integer or 'all'.",
            },
            "message_filter": {
                "type": "string",
                "required": False,
                "description": "One of 'all', 'exclude_tools', or 'only_tools'.",
            },
        },
        "return_shape": {
            "source": "Resolved history source.",
            "scope": "Resolved history scope.",
            "session_id": "Resolved session id.",
            "item_count": "Number of returned safe history units.",
            "items": "Ordered safe units: messages and atomic tool call/return exchanges.",
            "metadata": "Broker-owned retrieval metadata.",
        },
        "examples": [
            {
                "code": "history = await retrieve_history(scope='session', limit='all')",
                "description": "Read the active session history as safe atomic units.",
            }
        ],
    }
