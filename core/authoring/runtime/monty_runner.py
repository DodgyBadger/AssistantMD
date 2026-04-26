"""Minimal Monty runtime wrapper for the Monty-backed authoring surface."""

from __future__ import annotations

from dataclasses import dataclass, field
import keyword
from pathlib import Path
import re
from typing import Any

from pydantic_monty import Monty, run_monty_async

from core.authoring.helper_catalog import create_builtin_registry
from core.authoring.contracts import (
    AuthoringFinishSignal,
    AuthoringExecutionContext,
    AuthoringHost,
)
from core.authoring.helpers.runtime_common import invoke_bound_tool, normalize_tool_result
from core.authoring.registry import AuthoringCapabilityRegistry
from core.authoring.shared.tool_binding import resolve_tool_binding
from core.logger import UnifiedLogger
from core.settings.store import get_tools_config


logger = UnifiedLogger(tag="authoring-monty")

_STUBS_PATH = Path(__file__).parent.parent / "stubs.pyi"
_INVALID_IDENTIFIER_CHARS = re.compile(r"[^a-zA-Z0-9_]")
_EXCLUDED_DIRECT_TOOL_NAMES = frozenset({"code_execution_local"})


class AuthoringMontyExecutionError(RuntimeError):
    """Raised when Monty-backed authoring execution fails."""


@dataclass(frozen=True)
class AuthoringMontyExecutionResult:
    """Structured result from one Monty-backed authoring execution."""

    value: Any
    status: str = "completed"
    reason: str = ""
    prints: tuple[str, ...] = ()


@dataclass(frozen=True)
class _PrintCapture:
    lines: list[str] = field(default_factory=list)

    def callback(self, _channel: str, text: str) -> None:
        self.lines.append(text)


async def run_authoring_monty(
    *,
    workflow_id: str,
    code: str,
    host: AuthoringHost,
    inputs: dict[str, Any] | None = None,
    script_name: str = "main.py",
    type_check: bool = True,
    registry: AuthoringCapabilityRegistry | None = None,
) -> AuthoringMontyExecutionResult:
    """Execute one experimental authoring artifact with Monty."""
    runtime_registry = registry or create_builtin_registry()
    context = AuthoringExecutionContext(
        workflow_id=workflow_id,
        host=host,
    )
    external_functions = runtime_registry.build_external_functions(
        context=context,
    )
    direct_tool_functions, direct_tool_stubs = _build_direct_tool_functions(
        context=context,
    )
    external_functions.update(direct_tool_functions)
    reserved_inputs = dict(host.get_monty_inputs())
    effective_inputs = {**reserved_inputs, **(inputs or {})}
    capture = _PrintCapture()

    logger.add_sink("validation").info(
        "authoring_monty_execution_started",
        data={
            "workflow_id": workflow_id,
            "script_name": script_name,
            "type_check": type_check,
        },
    )

    terminal_status = "completed"
    terminal_reason = ""
    value: Any = None
    try:
        runner = Monty(
            code,
            script_name=script_name,
            inputs=sorted(effective_inputs) if effective_inputs else None,
            type_check=type_check,
            type_check_stubs=_build_type_check_stubs(direct_tool_stubs) if type_check else None,
        )
        for dataclass_type in host.get_monty_dataclasses():
            runner.register_dataclass(dataclass_type)

        try:
            value = await run_monty_async(
                runner,
                inputs=effective_inputs or None,
                external_functions=external_functions,
                print_callback=capture.callback,
            )
        except Exception as exc:
            parsed_finish = _extract_finish_signal(exc)
            if parsed_finish is not None:
                terminal_status, terminal_reason = parsed_finish
            else:
                raise
    except Exception as exc:
        logger.add_sink("validation").error(
            "authoring_monty_execution_failed",
            data={
                "workflow_id": workflow_id,
                "script_name": script_name,
                "error_message": str(exc),
                "error_type": type(exc).__name__,
            },
        )
        raise AuthoringMontyExecutionError(
            f"Monty execution failed for '{workflow_id}': {exc}"
        ) from exc

    logger.add_sink("validation").info(
        "authoring_monty_execution_completed",
        data={
            "workflow_id": workflow_id,
            "script_name": script_name,
            "status": terminal_status,
            "reason": terminal_reason,
            "printed_line_count": len(capture.lines),
        },
    )
    return AuthoringMontyExecutionResult(
        value=value,
        status=terminal_status,
        reason=terminal_reason,
        prints=tuple(capture.lines),
    )


def _build_type_check_stubs(direct_tool_stubs: str) -> str:
    base = _STUBS_PATH.read_text(encoding="utf-8")
    if not direct_tool_stubs:
        return base
    return f"{base}\n\n# Direct tool callables\n{direct_tool_stubs}"


def _build_direct_tool_functions(
    *,
    context: AuthoringExecutionContext,
) -> tuple[dict[str, Any], str]:
    host = context.host
    tool_names = [
        name
        for name in sorted(get_tools_config())
        if name not in _EXCLUDED_DIRECT_TOOL_NAMES
    ]
    if not tool_names:
        return {}, ""

    binding = resolve_tool_binding(
        tool_names,
        vault_path=host.vault_path or "",
        week_start_day=host.week_start_day,
    )
    external_functions: dict[str, Any] = {}
    stub_lines: list[str] = []
    used_names: set[str] = set()

    for spec in binding.tool_specs:
        function_name = _sanitize_tool_name(spec.name)
        if function_name in used_names:
            logger.warning(
                "Direct tool skipped due to Monty name collision",
                data={"tool": spec.name, "function_name": function_name},
            )
            continue
        used_names.add(function_name)

        async def _direct_tool_function(
            *args: Any,
            _spec: Any = spec,
            **kwargs: Any,
        ) -> Any:
            if args:
                raise ValueError(f"{_spec.name} only supports keyword arguments")
            logger.add_sink("validation").info(
                "authoring_direct_tool_started",
                data={
                    "workflow_id": context.workflow_id,
                    "tool": _spec.name,
                    "argument_keys": sorted(kwargs),
                },
            )
            result = await invoke_bound_tool(
                _spec.tool_function,
                tool_name=_spec.name,
                arguments=dict(kwargs),
                run_buffers=host.run_buffers,
                session_buffers=host.session_buffers,
                session_id=getattr(host, "session_key", None),
                chat_session_id=getattr(host, "chat_session_id", None),
                vault_name=str(context.workflow_id).split("/", 1)[0]
                if "/" in str(context.workflow_id)
                else None,
                message_history=getattr(host, "message_history", None),
            )
            tool_result = normalize_tool_result(
                _spec.name,
                result,
                vault_path=host.vault_path or "",
            )
            logger.add_sink("validation").info(
                "authoring_direct_tool_completed",
                data={
                    "workflow_id": context.workflow_id,
                    "tool": _spec.name,
                    "output_chars": len(tool_result.output),
                    "item_count": len(tool_result.items),
                    "has_content": tool_result.content is not None,
                },
            )
            return tool_result

        _direct_tool_function.__name__ = function_name
        _direct_tool_function.__doc__ = f"Direct Monty wrapper for tool '{spec.name}'."
        external_functions[function_name] = _direct_tool_function
        stub_lines.append(f"async def {function_name}(**kwargs: Any) -> ScriptToolResult: ...")

    return external_functions, "\n".join(stub_lines)


def _sanitize_tool_name(name: str) -> str:
    sanitized = _INVALID_IDENTIFIER_CHARS.sub("_", name)
    if sanitized and sanitized[0].isdigit():
        sanitized = f"_{sanitized}"
    if keyword.iskeyword(sanitized):
        sanitized = f"{sanitized}_"
    return sanitized or "_"


def _extract_finish_signal(exc: Exception) -> tuple[str, str] | None:
    direct = AuthoringFinishSignal.try_parse(str(exc))
    if direct is not None:
        return direct
    inner_exception = getattr(exc, "exception", None)
    if callable(inner_exception):
        inner = inner_exception()
        if inner is not None:
            return AuthoringFinishSignal.try_parse(str(inner))
    return None
