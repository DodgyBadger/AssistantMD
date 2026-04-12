"""Definition and execution for the call_tool(...) Monty helper."""

from __future__ import annotations

from typing import Any

from core.authoring.contracts import (
    AuthoringCapabilityCall,
    AuthoringCapabilityDefinition,
    AuthoringExecutionContext,
    CallToolResult,
)
from core.authoring.helpers.common import build_capability
from core.authoring.helpers.runtime_common import invoke_bound_tool, normalize_tool_result
from core.authoring.shared.tool_binding import resolve_tool_binding
from core.logger import UnifiedLogger


logger = UnifiedLogger(tag="authoring-host")


def build_definition() -> AuthoringCapabilityDefinition:
    return build_capability(
        name="call_tool",
        doc="Call one declared host tool and return its inline result plus metadata.",
        contract=_contract(),
        handler=execute,
    )


async def execute(
    call: AuthoringCapabilityCall,
    context: AuthoringExecutionContext,
) -> CallToolResult:
    host = context.host
    tool_name, arguments = _parse_call(call)
    logger.info(
        "authoring_call_tool_started",
        data={
            "workflow_id": context.workflow_id,
            "tool": tool_name,
            "argument_keys": sorted(arguments.keys()),
        },
    )
    logger.set_sinks(["validation"]).info(
        "authoring_call_tool_started",
        data={
            "workflow_id": context.workflow_id,
            "tool": tool_name,
            "argument_keys": sorted(arguments.keys()),
        },
    )

    binding = resolve_tool_binding(
        [tool_name],
        vault_path=host.vault_path or "",
        week_start_day=host.week_start_day,
    )
    tool_spec = next((spec for spec in binding.tool_specs if spec.name == tool_name), None)
    if tool_spec is None:
        raise ValueError(f"Resolved tool '{tool_name}' is unavailable in the current host context")

    result = await invoke_bound_tool(
        tool_spec.tool_function,
        tool_name=tool_name,
        arguments=arguments,
        run_buffers=host.run_buffers,
        session_buffers=host.session_buffers,
        session_id=getattr(host, "session_key", None),
        chat_session_id=getattr(host, "chat_session_id", None),
        vault_name=str(context.workflow_id).split("/", 1)[0] if "/" in str(context.workflow_id) else None,
        message_history=getattr(host, "message_history", None),
    )
    output, metadata = normalize_tool_result(result)
    logger.info(
        "authoring_call_tool_completed",
        data={
            "workflow_id": context.workflow_id,
            "tool": tool_name,
            "output_chars": len(output),
        },
    )
    logger.set_sinks(["validation"]).info(
        "authoring_call_tool_completed",
        data={
            "workflow_id": context.workflow_id,
            "tool": tool_name,
            "output_chars": len(output),
        },
    )
    return CallToolResult(
        name=tool_name,
        status="completed",
        output=output,
        metadata=metadata,
    )


def _parse_call(call: AuthoringCapabilityCall) -> tuple[str, dict[str, Any]]:
    if call.args:
        raise ValueError("call_tool only supports keyword arguments")
    tool_name = str(call.kwargs.get("name") or "").strip()
    if not tool_name:
        raise ValueError("call_tool requires a non-empty 'name'")
    raw_arguments = call.kwargs.get("arguments")
    if raw_arguments is None:
        arguments: dict[str, Any] = {}
    elif isinstance(raw_arguments, dict):
        arguments = dict(raw_arguments)
    else:
        raise ValueError("call_tool arguments must be a dictionary when provided")
    raw_options = call.kwargs.get("options")
    if raw_options is None:
        options: dict[str, Any] = {}
    elif isinstance(raw_options, dict):
        options = dict(raw_options)
    else:
        raise ValueError("call_tool options must be a dictionary when provided")
    if options:
        raise ValueError("call_tool options are reserved for future use and must currently be omitted")
    return tool_name, arguments


def _contract() -> dict[str, object]:
    return {
        "signature": "call_tool(*, name: str, arguments: dict | None = None, options: dict | None = None)",
        "summary": (
            "Call one declared host tool by configured tool name. Arguments are passed "
            "as keyword arguments to the tool. The current MVP returns inline output plus metadata only."
        ),
        "arguments": {
            "name": {
                "type": "string",
                "required": True,
                "description": "Configured runtime tool name.",
            },
            "arguments": {
                "type": "dict",
                "required": False,
                "description": "Keyword arguments forwarded directly to the resolved tool.",
            },
            "options": {
                "type": "dict",
                "required": False,
                "description": "Reserved for future host-side behavior. The MVP requires this to be empty or omitted.",
            },
        },
        "return_shape": {
            "name": "Configured tool name that was invoked.",
            "status": "High-level result status.",
            "output": "Inline textual tool result.",
            "metadata": "Host-owned metadata for result inspection and future expansion.",
        },
        "examples": [
            {
                "code": 'await call_tool(name="workflow_run", arguments={"operation": "list"})',
                "description": "List workflows in the current vault using the configured workflow tool.",
            },
            {
                "code": (
                    'await call_tool('
                    'name="internal_api", '
                    'arguments={"endpoint": "metadata"}'
                    ")"
                ),
                "description": "Read structured system metadata through an allowlisted internal tool.",
            },
        ],
    }
