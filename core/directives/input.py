"""Thin @input directive adapter over shared workflow input resolution."""

import re
from typing import Any, Dict, List, Optional

from .base import DirectiveProcessor
from .parser import DirectiveValueParser
from core.authoring.shared.input_resolution import (
    INPUT_ALLOWED_PARAMETERS,
    build_input_request,
    resolve_input_request,
)


class InputFileDirective(DirectiveProcessor):
    """Parse `@input` text, then delegate execution to shared typed runtime logic."""
    
    def get_directive_name(self) -> str:
        return "input"

    def _parse_input_target_and_parameters(self, value: str) -> tuple[str, Dict[str, str]]:
        base_value, parameters = DirectiveValueParser.parse_value_with_parameters(
            value.strip(),
            allowed_parameters=INPUT_ALLOWED_PARAMETERS,
        )
        if self._has_unparsed_known_param_assignment(
            value=value,
            allowed_parameters=INPUT_ALLOWED_PARAMETERS,
            parsed_parameters={k.lower() for k in parameters.keys()},
        ):
            raise ValueError(
                "Malformed parameter block. If a value contains commas, wrap it in quotes "
                '(e.g. properties="name,description").'
            )

        return base_value, {k.lower(): v for k, v in parameters.items()}

    def _has_unparsed_known_param_assignment(
        self,
        *,
        value: str,
        allowed_parameters: set[str],
        parsed_parameters: set[str],
    ) -> bool:
        stripped = value.rstrip()
        if not stripped.endswith(")"):
            return False

        depth = 0
        open_idx: Optional[int] = None
        for idx in range(len(stripped) - 1, -1, -1):
            char = stripped[idx]
            if char == ")":
                depth += 1
            elif char == "(":
                depth -= 1
                if depth == 0:
                    open_idx = idx
                    break
        if open_idx is None or depth != 0:
            return False

        params_section = stripped[open_idx + 1 : -1]
        assignment_keys = {
            key.lower()
            for key in re.findall(r"([A-Za-z_][A-Za-z0-9_-]*)\s*=", params_section)
        }
        known_assignment_keys = assignment_keys.intersection(allowed_parameters)
        return bool(known_assignment_keys - parsed_parameters)
    
    def validate_value(self, value: str) -> bool:
        if not value or not value.strip():
            return False

        try:
            base_value, parameters = self._parse_input_target_and_parameters(value.strip())
            if base_value.startswith("file:"):
                target = base_value[len("file:"):].strip()
                if not target or target.startswith("/") or ".." in target:
                    return False
            elif base_value.startswith("variable:"):
                target = base_value[len("variable:"):].strip()
                if not target:
                    return False
            else:
                return False
        except ValueError:
            return False

        return True
    
    def process_value(self, value: str, vault_path: str, **context) -> List[Dict[str, Any]]:
        """Process input via shared typed runtime input resolution."""
        value = value.strip()
        base_value, parameters = self._parse_input_target_and_parameters(value)
        if base_value.startswith("variable:"):
            target_type = "variable"
            target = base_value[len("variable:"):].strip()
        elif base_value.startswith("file:"):
            target_type = "file"
            target = base_value[len("file:"):].strip()
        else:
            raise ValueError("Input target must start with file: or variable:")
        request = build_input_request(
            target_type=target_type,
            target=target,
            parameters=parameters,
        )
        return resolve_input_request(
            request,
            vault_path=vault_path,
            reference_date=context.get("reference_date"),
            week_start_day=context.get("week_start_day", 0),
            state_manager=context.get("state_manager"),
            buffer_store=context.get("buffer_store"),
            buffer_store_registry=context.get("buffer_store_registry"),
            buffer_scope=context.get("buffer_scope", "run"),
            allow_context_output=bool(context.get("allow_context_output")),
        )
