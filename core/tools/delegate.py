"""Delegate tool - run a bounded child agent and return its output."""

import asyncio
import json
from collections.abc import Sequence
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturn,
    ToolReturnPart,
)
from pydantic_ai.tools import Tool
from pydantic_ai.usage import UsageLimits

from core.authoring.helpers.runtime_common import coerce_output_data
from core.authoring.shared.execution_prep import (
    _THINKING_UNSET,
    resolve_effective_thinking,
)
from core.authoring.shared.tool_binding import resolve_tool_binding
from core.constants import (
    DELEGATE_AUDIT_MAX_ARGUMENT_CHARS,
    DELEGATE_AUDIT_MAX_RESULT_CHARS,
    DELEGATE_AUDIT_MAX_TOOL_CALLS,
    DELEGATE_DEFAULT_MAX_TOOL_CALLS,
    DELEGATE_DEFAULT_TIMEOUT_SECONDS,
)
from core.llm.agents import create_agent
from core.llm.capabilities.assistant_tools import build_assistant_tools_capabilities
from core.llm.model_factory import build_model_instance
from core.llm.model_selection import ModelExecutionSpec
from core.llm.thinking import normalize_thinking_value, thinking_value_to_label
from core.logger import UnifiedLogger
from core.settings import get_default_model_thinking
from core.tools.base import BaseTool


logger = UnifiedLogger(tag="delegate-tool")

_FORBIDDEN_CHILD_TOOLS = frozenset({"delegate", "code_execution"})
_SUPPORTED_OPTION_KEYS = frozenset({"thinking"})


class DelegateTool(BaseTool):
    """Run a bounded child agent over a prompt with optional tools."""

    @classmethod
    def get_tool(cls, vault_path: str = None) -> Tool:
        _vault_path = vault_path or ""

        async def delegate(
            ctx: RunContext,
            prompt: str,
            instructions: str | None = None,
            model: str | None = None,
            tools: list[str] | None = None,
            options: dict | None = None,
        ) -> ToolReturn:
            """Run a focused child agent over a prompt with optional tools.

            :param prompt: Primary prompt for the child agent.
            :param instructions: Optional system-style instructions for the child agent.
            :param model: Optional model alias.
            :param tools: Optional list of tool names available to the child agent.
            :param options: Optional controls: thinking.
            """
            session_id = getattr(ctx.deps, "session_id", None) or "delegate"

            prompt = str(prompt or "").strip()
            if not prompt:
                raise ValueError("delegate requires a non-empty 'prompt'")

            model_value = str(model).strip() if model else None
            tool_names = _parse_tool_names(tools)
            requested_thinking, max_tool_calls, timeout_seconds = _parse_options(options or {})

            safe_tool_names = tuple(n for n in tool_names if n not in _FORBIDDEN_CHILD_TOOLS)
            stripped = tuple(sorted(set(tool_names) - set(safe_tool_names)))

            resolved_thinking, thinking_source = resolve_effective_thinking(
                requested_thinking=requested_thinking,
                default_thinking=get_default_model_thinking(),
            )

            logger.add_sink("validation").info(
                "delegate_started",
                data={
                    "workflow_id": session_id,
                    "model": model_value or "default",
                    "tool_names": list(safe_tool_names),
                    "stripped_tools": list(stripped),
                    "resolved_thinking": thinking_value_to_label(resolved_thinking),
                    "thinking_source": thinking_source,
                    "max_tool_calls": max_tool_calls,
                    "timeout_seconds": timeout_seconds,
                },
            )

            resolved_model = None
            if model_value:
                resolved_model = build_model_instance(model_value, thinking=resolved_thinking)
                if isinstance(resolved_model, ModelExecutionSpec) and resolved_model.mode == "skip":
                    raise ValueError("delegate does not support skip model mode")

            tool_capabilities = None
            if safe_tool_names:
                week_start_day = getattr(ctx.deps, "week_start_day", 0)
                binding = resolve_tool_binding(
                    list(safe_tool_names),
                    vault_path=_vault_path,
                    week_start_day=week_start_day,
                )
                tool_capabilities = build_assistant_tools_capabilities(
                    tools=binding.tool_functions,
                    instructions="",
                )
                logger.add_sink("validation").info(
                    "delegate_tool_binding_resolved",
                    data={
                        "workflow_id": session_id,
                        "requested": list(safe_tool_names),
                        "bound": binding.tool_names(),
                    },
                )

            try:
                agent = await create_agent(
                    model=resolved_model,
                    capabilities=tool_capabilities,
                    thinking=resolved_thinking,
                )
                if instructions:
                    agent.instructions(lambda _ctx, text=instructions: text)

                usage_limits = UsageLimits(tool_calls_limit=max_tool_calls)
                run_coro = agent.run(prompt, usage_limits=usage_limits)
                result = await asyncio.wait_for(run_coro, timeout=timeout_seconds)
                output = result.output
                text = coerce_output_data(output)
                audit = _build_child_run_audit(result.all_messages())
            except UsageLimitExceeded as exc:
                return _failed_delegate_return(
                    session_id=session_id,
                    model=model_value or "default",
                    tool_names=safe_tool_names,
                    stripped_tools=stripped,
                    thinking=thinking_value_to_label(resolved_thinking),
                    max_tool_calls=max_tool_calls,
                    timeout_seconds=timeout_seconds,
                    error_type=type(exc).__name__,
                    message=(
                        f"Delegate stopped because the child agent exceeded its tool-call limit "
                        f"of {max_tool_calls}. Do not retry the same broad delegation. Split the work into "
                        "smaller delegate calls scoped by path, query, source group, or hypothesis; use direct "
                        "deterministic tools for simple retrieval; and have each child return a compact summary "
                        "or saved artifact path."
                    ),
                )
            except asyncio.TimeoutError as exc:
                return _failed_delegate_return(
                    session_id=session_id,
                    model=model_value or "default",
                    tool_names=safe_tool_names,
                    stripped_tools=stripped,
                    thinking=thinking_value_to_label(resolved_thinking),
                    max_tool_calls=max_tool_calls,
                    timeout_seconds=timeout_seconds,
                    error_type=type(exc).__name__,
                    message=(
                        f"Delegate stopped because the child agent exceeded its timeout of "
                        f"{timeout_seconds:g} seconds. Do not retry the same broad delegation. Split the work "
                        "into smaller delegate calls, narrow the file/web scope, or ask the child to save an "
                        "intermediate artifact and return only a compact summary/path."
                    ),
                )
            except Exception as exc:
                logger.add_sink("validation").error(
                    "delegate_failed",
                    data={
                        "workflow_id": session_id,
                        "model": model_value or "default",
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    },
                )
                raise

            metadata: dict[str, Any] = {
                "status": "completed",
                "model": model_value or "default",
                "tool_names": list(safe_tool_names),
                "thinking": thinking_value_to_label(resolved_thinking),
                "output_chars": len(text),
                "max_tool_calls": max_tool_calls,
                "timeout_seconds": timeout_seconds,
                "audit": audit,
            }
            if stripped:
                metadata["stripped_tools"] = list(stripped)

            logger.add_sink("validation").info(
                "delegate_completed",
                data={
                    "workflow_id": session_id,
                    "model": model_value or "default",
                    "tool_names": list(safe_tool_names),
                    "output_chars": len(text),
                    "child_tool_call_count": audit["tool_call_count"],
                    "child_tool_error_count": audit["tool_error_count"],
                    "max_tool_calls": max_tool_calls,
                    "timeout_seconds": timeout_seconds,
                },
            )

            return ToolReturn(return_value=text, content=None, metadata=metadata)

        return Tool(
            delegate,
            takes_ctx=True,
            name="delegate",
            description="Run a focused child agent over a prompt with optional tools.",
        )

    @classmethod
    def get_instructions(cls) -> str:
        return """
Full documentation:
- `__virtual_docs__/tools/delegate.md`
"""


def _failed_delegate_return(
    *,
    session_id: str,
    model: str,
    tool_names: tuple[str, ...],
    stripped_tools: tuple[str, ...],
    thinking: str,
    max_tool_calls: int,
    timeout_seconds: float,
    error_type: str,
    message: str,
) -> ToolReturn:
    metadata: dict[str, Any] = {
        "status": "failed",
        "model": model,
        "tool_names": list(tool_names),
        "thinking": thinking,
        "output_chars": len(message),
        "max_tool_calls": max_tool_calls,
        "timeout_seconds": timeout_seconds,
        "error_type": error_type,
        "audit": _empty_child_run_audit(),
    }
    if stripped_tools:
        metadata["stripped_tools"] = list(stripped_tools)

    logger.add_sink("validation").warning(
        "delegate_failed",
        data={
            "workflow_id": session_id,
            "model": model,
            "tool_names": list(tool_names),
            "error_type": error_type,
            "error_message": message,
            "max_tool_calls": max_tool_calls,
            "timeout_seconds": timeout_seconds,
        },
    )
    return ToolReturn(return_value=message, content=None, metadata=metadata)


def _build_child_run_audit(messages: Sequence[ModelMessage]) -> dict[str, Any]:
    tool_calls_by_id: dict[str, dict[str, Any]] = {}
    total_tool_call_count = 0
    tool_calls: list[dict[str, Any]] = []
    response_count = 0
    request_count = 0

    for message in messages:
        if isinstance(message, ModelRequest):
            request_count += 1
        elif isinstance(message, ModelResponse):
            response_count += 1

        for part in getattr(message, "parts", ()) or ():
            if isinstance(part, ToolCallPart):
                total_tool_call_count += 1
                call = {
                    "tool": part.tool_name,
                    "call_id": part.tool_call_id,
                    "arguments": _compact_value(
                        part.args,
                        max_chars=DELEGATE_AUDIT_MAX_ARGUMENT_CHARS,
                    ),
                }
                if len(tool_calls) < DELEGATE_AUDIT_MAX_TOOL_CALLS:
                    tool_calls.append(call)
                    tool_calls_by_id[part.tool_call_id] = call
            elif isinstance(part, ToolReturnPart):
                call = tool_calls_by_id.get(part.tool_call_id)
                if call is None:
                    continue
                call["outcome"] = part.outcome
                call["result"] = _compact_value(
                    part.content,
                    max_chars=DELEGATE_AUDIT_MAX_RESULT_CHARS,
                )
                if isinstance(part.metadata, dict):
                    call["metadata"] = _compact_mapping(part.metadata)

    tool_error_count = sum(
        1
        for call in tool_calls
        if call.get("outcome") in {"failed", "denied"}
        or _looks_like_tool_error(str(call.get("result") or ""))
    )
    return {
        "message_count": len(messages),
        "request_count": request_count,
        "response_count": response_count,
        "tool_call_count": total_tool_call_count,
        "tool_error_count": tool_error_count,
        "tool_calls_truncated": total_tool_call_count > len(tool_calls),
        "tool_calls": tool_calls,
    }


def _empty_child_run_audit() -> dict[str, Any]:
    return {
        "message_count": 0,
        "request_count": 0,
        "response_count": 0,
        "tool_call_count": 0,
        "tool_error_count": 0,
        "tool_calls_truncated": False,
        "tool_calls": [],
    }


def _compact_mapping(value: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in (
        "status",
        "operation",
        "path",
        "media_type",
        "media_mode",
        "size_bytes",
        "error_type",
    ):
        if key in value:
            compact[key] = _compact_value(value[key], max_chars=200)
    return compact


def _compact_value(value: Any, *, max_chars: int) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except TypeError:
            text = str(value)
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}...[truncated {len(text) - max_chars} chars]"


def _looks_like_tool_error(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "error",
            "cannot ",
            "not found",
            "unsupported",
            "permission denied",
            "exceeded",
            "timeout",
        )
    )


def _parse_tool_names(tools: Any) -> tuple[str, ...]:
    if tools is None:
        return ()
    if isinstance(tools, (list, tuple)):
        result: list[str] = []
        for item in tools:
            if not isinstance(item, str):
                raise ValueError("delegate tools entries must be strings")
            name = item.strip()
            if name:
                result.append(name)
        return tuple(result)
    raise ValueError("delegate tools must be a list or tuple of strings when provided")


def _parse_options(options: dict[str, Any]) -> tuple[object, int, float]:
    unknown = sorted(set(options) - _SUPPORTED_OPTION_KEYS)
    if unknown:
        raise ValueError(f"Unsupported delegate options: {', '.join(unknown)}")

    if "thinking" not in options:
        requested_thinking: object = _THINKING_UNSET
    else:
        requested_thinking = normalize_thinking_value(
            options["thinking"], source_name="delegate option 'thinking'"
        )

    return (
        requested_thinking,
        DELEGATE_DEFAULT_MAX_TOOL_CALLS,
        DELEGATE_DEFAULT_TIMEOUT_SECONDS,
    )
