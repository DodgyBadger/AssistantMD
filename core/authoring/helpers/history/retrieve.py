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
)
from core.authoring.helpers.common import build_capability
from core.memory import MemoryContext, MemoryService
from core.logger import UnifiedLogger


_MEMORY_SERVICE = MemoryService()
logger = UnifiedLogger(tag="authoring-host")


def build_definition() -> AuthoringCapabilityDefinition:
    return build_capability(
        name="retrieve_history",
        doc=(
            "Retrieve structured conversation history directly from the shared memory broker. "
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
    logger.add_sink("validation").info(
        "authoring_retrieve_history_started",
        data={
            "workflow_id": context.workflow_id,
            "scope": scope,
            "session_id": session_id or getattr(host, "chat_session_id", None) or getattr(host, "session_key", None),
            "limit": limit,
            "message_filter": message_filter,
        },
    )
    result = _MEMORY_SERVICE.get_conversation_history(
        context=MemoryContext(
            message_history=tuple(getattr(host, "message_history", []) or ()),
            session_id=getattr(host, "chat_session_id", None) or getattr(host, "session_key", None),
            vault_name=str(context.workflow_id).split("/", 1)[0] if "/" in str(context.workflow_id) else None,
        ),
        scope=scope,
        session_id=session_id,
        limit=limit,
        message_filter=message_filter,
    )
    items = tuple(_build_safe_history_items(result.items))
    response = RetrievedHistoryResult(
        source=result.source,
        scope=result.scope,
        session_id=result.session_id,
        item_count=len(items),
        items=items,
        metadata=dict(result.metadata),
    )
    logger.add_sink("validation").info(
        "authoring_retrieve_history_completed",
        data={
            "workflow_id": context.workflow_id,
            "scope": response.scope,
            "session_id": response.session_id,
            "item_count": response.item_count,
            "source": response.source,
            "message_filter": response.metadata.get("message_filter"),
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


def _build_safe_history_items(items: tuple[Any, ...]) -> list[HistoryMessage | ToolExchange]:
    safe_items: list[HistoryMessage | ToolExchange] = []
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
) -> tuple[ToolExchange | None, int]:
    first = items[start_index]
    first_message = first.message if isinstance(getattr(first, "message", None), dict) else None
    if first_message is None or str(getattr(first, "message_type", "") or "") != "ModelResponse":
        return None, 1

    first_parts = list(first_message.get("parts") or ())
    tool_call_parts = [part for part in first_parts if part.get("part_kind") == "tool-call"]
    if len(tool_call_parts) != 1:
        return None, 1

    tool_call_part = tool_call_parts[0]
    tool_call_id = str(tool_call_part.get("tool_call_id") or "").strip()
    tool_name = str(tool_call_part.get("tool_name") or "").strip()
    if not tool_call_id or not tool_name:
        return None, 1

    if start_index + 1 >= len(items):
        return None, 1
    second = items[start_index + 1]
    second_message = second.message if isinstance(getattr(second, "message", None), dict) else None
    if second_message is None or str(getattr(second, "message_type", "") or "") != "ModelRequest":
        return None, 1

    second_parts = list(second_message.get("parts") or ())
    tool_return_parts = [part for part in second_parts if part.get("part_kind") == "tool-return"]
    if len(tool_return_parts) != 1:
        return None, 1

    tool_return_part = tool_return_parts[0]
    if str(tool_return_part.get("tool_call_id") or "").strip() != tool_call_id:
        return None, 1

    call_arguments = tool_call_part.get("args")
    if not isinstance(call_arguments, dict):
        call_arguments = None
    result_text = tool_return_part.get("content")
    if result_text is not None:
        result_text = str(result_text)

    metadata = dict(getattr(first, "metadata", {}) or {})
    metadata.update(dict(getattr(second, "metadata", {}) or {}))
    return (
        ToolExchange(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            request_message=dict(first_message),
            response_message=dict(second_message),
            call_arguments=call_arguments,
            result_text=result_text,
            metadata=metadata,
        ),
        2,
    )


def _contract() -> dict[str, object]:
    return {
        "signature": (
            "retrieve_history(*, scope: str = 'session', session_id: str | None = None, "
            "limit: int | str = 'all', message_filter: str = 'all')"
        ),
        "summary": (
            "Retrieve conversation history directly from the shared memory broker. "
            "Tool call/return pairs are returned as one atomic tool exchange."
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
            "item_count": "Number of returned history items.",
            "items": "Ordered safe history units (messages and atomic tool exchanges).",
            "metadata": "Broker-owned retrieval metadata.",
        },
        "examples": [
            {
                "code": "history = await retrieve_history(scope='session', limit='all')",
                "description": "Read the active session history as safe atomic units.",
            }
        ],
    }
