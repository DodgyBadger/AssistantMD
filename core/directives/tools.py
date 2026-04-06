"""Thin @tools directive adapter over shared workflow tool binding."""

from __future__ import annotations

from typing import List, Tuple

from .base import DirectiveProcessor
from core.authoring.shared.tool_binding import (
    ToolBindingResult,
    ToolSpec,
    merge_tool_bindings,
    resolve_tool_binding,
    validate_tool_binding_value,
)


class ToolsDirective(DirectiveProcessor):
    """Processor for @tools directive that delegates to shared tool binding."""

    ToolSpec = ToolSpec

    def get_directive_name(self) -> str:
        return "tools"

    def validate_value(self, value: str) -> bool:
        return validate_tool_binding_value(value)

    def process_value(self, value: str, vault_path: str, **context) -> Tuple[List, str, List[ToolSpec]]:
        binding = resolve_tool_binding(
            value,
            vault_path=vault_path,
            week_start_day=context.get("week_start_day", 0),
        )
        return binding.tool_functions, binding.tool_instructions, binding.tool_specs

    @staticmethod
    def merge_results(results: List[Tuple] | List[ToolBindingResult]) -> Tuple[List, str, List[ToolSpec]]:
        binding = merge_tool_bindings(results)
        return binding.tool_functions, binding.tool_instructions, binding.tool_specs
