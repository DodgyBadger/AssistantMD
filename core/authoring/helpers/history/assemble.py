"""Definition and execution for the assemble_context(...) Monty helper."""

from __future__ import annotations

from typing import Any

from core.authoring.contracts import (
    AssembleContextResult,
    AuthoringCapabilityCall,
    AuthoringCapabilityDefinition,
    AuthoringExecutionContext,
    ContextMessage,
    HistoryMessage,
    ToolExchange,
)
from core.authoring.helpers.common import build_capability
from core.authoring.helpers.runtime_common import (
    normalize_context_message,
    normalize_object_sequence,
    normalize_optional_string,
)
from core.logger import UnifiedLogger


logger = UnifiedLogger(tag="authoring-host")


def build_definition() -> AuthoringCapabilityDefinition:
    return build_capability(
        name="assemble_context",
        doc=(
            "Assemble validated structured chat context from broker-derived history, "
            "instructions, and explicit latest-user input."
        ),
        contract=_contract(),
        handler=execute,
    )


async def execute(
    call: AuthoringCapabilityCall,
    context: AuthoringExecutionContext,
) -> AssembleContextResult:
    history, context_messages, instructions, latest_user_message = _parse_call(call)
    assembled_messages: list[Any] = []

    if instructions:
        assembled_messages.append(ContextMessage(role="system", content=instructions))
    for item in context_messages:
        assembled_messages.append(_normalize_history_context_item(item, default_role="system"))
    for item in history:
        assembled_messages.append(_normalize_history_context_item(item))
    if latest_user_message is not None:
        assembled_messages.append(_normalize_history_context_item(latest_user_message, default_role="user"))

    logger.add_sink("validation").info(
        "authoring_assemble_context_completed",
        data={
            "workflow_id": context.workflow_id,
            "message_count": len(assembled_messages),
            "instruction_count": 1 if instructions else 0,
        },
    )

    return AssembleContextResult(
        messages=tuple(assembled_messages),
        instructions=(instructions,) if instructions else (),
    )


def _normalize_history_context_item(value: Any, *, default_role: str | None = None) -> Any:
    if isinstance(value, (ContextMessage, HistoryMessage, ToolExchange)):
        return value
    return normalize_context_message(value, default_role=default_role)


def _parse_call(
    call: AuthoringCapabilityCall,
) -> tuple[tuple[Any, ...], tuple[Any, ...], str | None, Any | None]:
    if call.args:
        raise ValueError("assemble_context only supports keyword arguments")
    history = normalize_object_sequence(
        call.kwargs.get("history"),
        field_name="assemble_context history",
    )
    context_messages = normalize_object_sequence(
        call.kwargs.get("context_messages"),
        field_name="assemble_context context_messages",
    )
    instructions = normalize_optional_string(
        call.kwargs.get("instructions"),
        field_name="assemble_context instructions",
    )
    latest_user_message = call.kwargs.get("latest_user_message")
    return history, context_messages, instructions, latest_user_message


def _contract() -> dict[str, object]:
    return {
        "signature": (
            "assemble_context(*, history: list | tuple | None = None, "
            "context_messages: list | tuple | None = None, "
            "instructions: str | None = None, "
            "latest_user_message: object | None = None)"
        ),
        "summary": (
            "Build validated downstream chat context from safe history units and "
            "explicit instruction/context layers."
        ),
        "arguments": {
            "history": {
                "type": "list|tuple",
                "required": False,
                "description": (
                    "Structured history items to preserve in order. Supports broker-derived "
                    "HistoryMessage and ToolExchange values."
                ),
            },
            "context_messages": {
                "type": "list|tuple",
                "required": False,
                "description": "Additional system-context messages injected ahead of preserved history.",
            },
            "instructions": {
                "type": "string",
                "required": False,
                "description": "Extra downstream chat instructions injected as one additional system message.",
            },
            "latest_user_message": {
                "type": "object",
                "required": False,
                "description": "Optional explicit latest user message appended last.",
            },
        },
        "return_shape": {
            "messages": "Validated downstream context items.",
            "instructions": "Normalized downstream instruction strings included in assembly.",
        },
        "examples": [
            {
                "code": "history = await retrieve_history(scope='session')\nfinal = await assemble_context(history=history.items)",
                "description": "Preserve recent chat history as structured downstream context.",
            },
            {
                "code": (
                    "history = await retrieve_history(scope='session')\n"
                    "final = await assemble_context(\n"
                    "    history=history.items,\n"
                    "    instructions='Prefer exact quoted text when possible.',\n"
                    ")\n"
                ),
                "description": "Add downstream instructions without flattening preserved history by default.",
            },
        ],
    }
