"""Definition and execution for the assemble_context(...) Monty helper."""

from __future__ import annotations

from typing import Any

from core.authoring.contracts import (
    AssembleContextResult,
    AuthoringCapabilityCall,
    AuthoringCapabilityDefinition,
    AuthoringExecutionContext,
    ContextMessage,
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
            "Assemble validated structured chat context from retrieved history, "
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
    assembled_messages: list[ContextMessage] = []

    if instructions:
        assembled_messages.append(ContextMessage(role="system", content=instructions))
    for item in context_messages:
        assembled_messages.append(normalize_context_message(item, default_role="system"))
    for item in history:
        assembled_messages.append(normalize_context_message(item))
    if latest_user_message is not None:
        assembled_messages.append(normalize_context_message(latest_user_message, default_role="user"))

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
            "Build validated structured downstream chat context from retrieved history "
            "and explicit instruction/context layers."
        ),
        "arguments": {
            "history": {
                "type": "list|tuple",
                "required": False,
                "description": "Structured message-like items to preserve in order.",
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
            "messages": [
                {
                    "role": "Normalized role such as system, user, or assistant.",
                    "content": "Text content for the downstream chat message.",
                    "metadata": "Host-owned metadata retained from normalization.",
                }
            ],
            "instructions": "Normalized downstream instruction strings included in assembly.",
        },
        "examples": [
            {
                "code": (
                    'history = await retrieve(type="run", ref="session", options={"limit": 3})\n'
                    "final = await assemble_context(history=history.items)"
                ),
                "description": "Preserve recent chat history as structured downstream context.",
            },
            {
                "code": (
                    'history = await retrieve(type="run", ref="session", options={"limit": 3})\n'
                    "final = await assemble_context(\n"
                    "    history=history.items,\n"
                    '    instructions="Prefer exact quoted text when possible.",\n'
                    ")\n"
                ),
                "description": "Add downstream instructions without flattening them into the transcript.",
            },
        ],
    }
