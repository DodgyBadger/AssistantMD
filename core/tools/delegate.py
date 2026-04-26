"""Delegate tool — run a bounded child agent and return its output."""

from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.messages import ToolReturn
from pydantic_ai.tools import Tool

from core.authoring.helpers.runtime_common import coerce_output_data
from core.authoring.shared.execution_prep import (
    _THINKING_UNSET,
    resolve_effective_thinking,
)
from core.authoring.shared.tool_binding import resolve_tool_binding
from core.llm.agents import create_agent, generate_response
from core.llm.capabilities.assistant_tools import build_assistant_tools_capabilities
from core.llm.model_factory import build_model_instance
from core.llm.model_selection import ModelExecutionSpec
from core.llm.thinking import normalize_thinking_value, thinking_value_to_label
from core.logger import UnifiedLogger
from core.settings import get_default_model_thinking
from core.tools.base import BaseTool


logger = UnifiedLogger(tag="delegate-tool")

_FORBIDDEN_CHILD_TOOLS = frozenset({"delegate", "code_execution_local"})
_SUPPORTED_OPTION_KEYS = frozenset({"thinking", "max_tool_calls", "timeout_seconds", "history"})


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
            :param options: Optional controls: thinking, max_tool_calls, timeout_seconds, history.
            """
            session_id = getattr(ctx.deps, "session_id", None) or "delegate"

            prompt = str(prompt or "").strip()
            if not prompt:
                raise ValueError("delegate requires a non-empty 'prompt'")

            model_value = str(model).strip() if model else None
            tool_names = _parse_tool_names(tools)
            requested_thinking, max_tool_calls = _parse_options(options or {})

            safe_tool_names = tuple(n for n in tool_names if n not in _FORBIDDEN_CHILD_TOOLS)
            stripped = set(tool_names) - set(safe_tool_names)

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

                output = await generate_response(agent, prompt)
                text = coerce_output_data(output)
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
                },
            )

            return ToolReturn(return_value=text, content=None, metadata=metadata)

        return Tool(delegate, takes_ctx=True, name="delegate", description=cls.get_instructions())

    @classmethod
    def get_instructions(cls) -> str:
        return (
            "Use delegate to run a focused child agent over a prompt with optional tools. "
            "The child agent returns a single text response. "
            "Provide prompt (required), instructions (optional system guidance), "
            "model (optional alias), tools (optional list of tool names), "
            "and options (optional: thinking, max_tool_calls). "
            "To work with files, include file paths in the prompt and provide relevant tools "
            "such as file_ops_safe so the child agent can read them directly."
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


def _parse_options(options: dict[str, Any]) -> tuple[object, int | None]:
    unknown = sorted(set(options) - _SUPPORTED_OPTION_KEYS)
    if unknown:
        raise ValueError(f"Unsupported delegate options: {', '.join(unknown)}")

    if "history" in options:
        history = str(options["history"]).strip().lower()
        if history != "none":
            raise ValueError("delegate options.history only supports 'none' currently")

    if "thinking" not in options:
        requested_thinking: object = _THINKING_UNSET
    else:
        requested_thinking = normalize_thinking_value(
            options["thinking"], source_name="delegate option 'thinking'"
        )

    max_tool_calls: int | None = None
    if "max_tool_calls" in options:
        raw = options["max_tool_calls"]
        if not isinstance(raw, int) or raw <= 0:
            raise ValueError("delegate options.max_tool_calls must be a positive integer")
        max_tool_calls = raw

    return requested_thinking, max_tool_calls
