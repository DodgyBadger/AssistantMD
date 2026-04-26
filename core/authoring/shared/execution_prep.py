"""Shared step execution preparation for workflow authoring surfaces."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

from core.chunking.prompt_builder import PromptInput, build_input_files_prompt
from core.constants import WORKFLOW_SYSTEM_INSTRUCTION
from core.llm.model_selection import ModelExecutionSpec, resolve_model_execution_spec
from core.llm.model_utils import model_supports_capability
from core.llm.thinking import ThinkingValue

_THINKING_UNSET = object()


def resolve_step_model_execution(model_value: Any) -> ModelExecutionSpec:
    """Resolve shared model execution semantics for workflow steps."""
    if isinstance(model_value, ModelExecutionSpec):
        return model_value
    if isinstance(model_value, str) and model_value.strip():
        if model_value.strip().lower() == "test":
            return resolve_model_execution_spec(None)
        return resolve_model_execution_spec(model_value.strip())
    return resolve_model_execution_spec(None)


def normalize_run_on_days(value: Any) -> list[str]:
    """Normalize run_on values from either directive or typed SDK extras."""
    if value is None:
        return []
    if isinstance(value, str):
        candidate = value.strip().lower()
        return [candidate] if candidate else []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        days: list[str] = []
        for item in value:
            if isinstance(item, str):
                normalized = item.strip().lower()
                if normalized:
                    days.append(normalized)
        return days
    return []


def should_step_run_today(
    run_on_value: Any,
    *,
    today: datetime,
    single_step_name: str | None = None,
) -> bool:
    """Return whether a step should run today under shared run_on semantics."""
    if single_step_name:
        return True
    run_on_days = normalize_run_on_days(run_on_value)
    if not run_on_days:
        return True
    if "never" in run_on_days:
        return False
    if "daily" in run_on_days:
        return True
    today_name = today.strftime("%A").lower()
    today_abbrev = today.strftime("%a").lower()
    return today_name in run_on_days or today_abbrev in run_on_days


def build_step_prompt(
    *,
    base_prompt: str,
    input_file_data: Any,
    vault_path: str,
    model_execution: ModelExecutionSpec,
) -> tuple[PromptInput, str, int, list[str]]:
    """Build a prompt payload with shared input/media handling."""
    if not input_file_data:
        return base_prompt, base_prompt, 0, []

    supports_vision = (
        False
        if model_execution.mode == "skip"
        else (
            model_supports_capability(model_execution.raw_alias, "vision")
            if model_execution.raw_alias
            else None
        )
    )
    built = build_input_files_prompt(
        input_file_data=input_file_data,
        vault_path=vault_path,
        base_prompt=base_prompt,
        supports_vision=supports_vision,
    )
    return built.prompt, built.prompt_text, built.attached_image_count, built.warnings


def resolve_effective_thinking(
    *,
    requested_thinking: object,
    default_thinking: ThinkingValue,
) -> tuple[ThinkingValue, str]:
    """Resolve the effective thinking value from an explicit request and the global default."""
    if requested_thinking is not _THINKING_UNSET:
        return requested_thinking, "call_override"  # type: ignore[return-value]
    if default_thinking is not None:
        return default_thinking, "global_default"
    return None, "provider_default"


def compose_instruction_layers(
    *,
    workflow_instructions: str | None,
    tool_instructions: str | None,
    base_instructions_fallback: str | None = None,
) -> list[str]:
    """Compose shared workflow/system/tool instruction layers."""
    base_instructions = workflow_instructions or base_instructions_fallback or ""
    workflow_with_system = (
        f"{base_instructions}\n\n{WORKFLOW_SYSTEM_INSTRUCTION}".strip()
        if base_instructions
        else WORKFLOW_SYSTEM_INSTRUCTION.strip()
    )
    layers = [workflow_with_system]
    if tool_instructions:
        layers.append(tool_instructions)
    return [layer for layer in layers if layer]
