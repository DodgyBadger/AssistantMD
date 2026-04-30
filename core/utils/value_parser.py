"""Centralized value parsing utilities for directive and configuration surfaces.

Extracted from core.directives.parser so non-DSL modules can use these
utilities without depending on the directive execution machinery.
"""

from __future__ import annotations

import re
from typing import Dict, List


class DirectiveValueParser:
    """Centralized parsing service for directive values.

    Provides consistent value parsing across all directive processors to eliminate
    parsing inconsistencies and enable reliable @tools directive implementation.
    """

    @staticmethod
    def is_empty(value: str) -> bool:
        """Check if value is empty or whitespace-only."""
        return not value or not value.strip()

    @staticmethod
    def normalize_string(value: str, to_lower: bool = True) -> str:
        """Normalize string value consistently."""
        normalized = value.strip()
        return normalized.lower() if to_lower else normalized

    @staticmethod
    def parse_list(value: str, to_lower: bool = True) -> List[str]:
        """Parse space/comma-separated values consistently.

        Supports both formats:
        - Comma-separated: "monday, tuesday, wednesday"
        - Space-separated: "monday tuesday wednesday"
        - Mixed: "monday, tuesday wednesday"

        Args:
            value: The string to parse
            to_lower: Whether to normalize items to lowercase

        Returns:
            List of parsed, trimmed, non-empty items
        """
        if DirectiveValueParser.is_empty(value):
            return []

        items = [
            item.strip() for item in re.split(r'[,\s]+', value.strip()) if item.strip()
        ]

        if to_lower:
            items = [item.lower() for item in items]

        return items

    @staticmethod
    def parse_boolean(value: str) -> bool:
        """Parse boolean values consistently.

        Treats these as True: 'true', 'yes', '1', 'on' (case-insensitive)
        Treats empty/missing value as True (for directives like @tools)
        Everything else as False

        Args:
            value: The string to parse

        Returns:
            Boolean value
        """
        if DirectiveValueParser.is_empty(value):
            return True

        normalized = value.strip().lower()
        return normalized in ['true', 'yes', '1', 'on']

    @staticmethod
    def validate_from_set(value: str, valid_values: set, to_lower: bool = True) -> bool:
        """Validate that a single value exists in a set of valid values.

        Args:
            value: The value to validate
            valid_values: Set of acceptable values
            to_lower: Whether to normalize for comparison

        Returns:
            True if value is in the valid set
        """
        if DirectiveValueParser.is_empty(value):
            return False

        normalized = DirectiveValueParser.normalize_string(value, to_lower)
        comparison_set = {v.lower() for v in valid_values} if to_lower else valid_values
        return normalized in comparison_set

    @staticmethod
    def validate_list_from_set(
        value: str, valid_values: set, to_lower: bool = True
    ) -> bool:
        """Validate that all items in a list exist in a set of valid values.

        Args:
            value: The comma/space-separated string to validate
            valid_values: Set of acceptable values
            to_lower: Whether to normalize for comparison

        Returns:
            True if all parsed items are in the valid set
        """
        items = DirectiveValueParser.parse_list(value, to_lower)
        if not items:
            return False

        comparison_set = {v.lower() for v in valid_values} if to_lower else valid_values
        return all(item in comparison_set for item in items)

    @staticmethod
    def parse_value_with_parameters(
        value: str, allowed_parameters: set[str] | None = None
    ) -> tuple[str, Dict[str, str]]:
        """Parse a value that may contain parameters in parentheses.

        Supports formats like:
        - "sonnet" -> ("sonnet", {})
        - "sonnet (thinking)" -> ("sonnet", {"thinking": "true"})
        - "sonnet (thinking=true)" -> ("sonnet", {"thinking": "true"})
        - "sonnet (thinking=false, temperature=0.5)" -> (
            "sonnet",
            {"thinking": "false", "temperature": "0.5"},
          )

        Args:
            value: The directive value to parse
            allowed_parameters: Optional set of allowed parameter names

        Returns:
            Tuple of (base_value, parameters_dict)
        """
        if DirectiveValueParser.is_empty(value):
            return "", {}

        value = value.strip()
        allowed_normalized = (
            {param.lower() for param in allowed_parameters}
            if allowed_parameters
            else None
        )

        def parse_parameters(params_str: str) -> Dict[str, str] | None:
            if not params_str:
                return None

            param_items: List[str] = []
            buf: List[str] = []
            quote_char: str | None = None
            for ch in params_str:
                if ch in {"'", '"'}:
                    if quote_char is None:
                        quote_char = ch
                    elif quote_char == ch:
                        quote_char = None
                    buf.append(ch)
                    continue
                if ch == "," and quote_char is None:
                    token = "".join(buf).strip()
                    if token:
                        param_items.append(token)
                    buf = []
                    continue
                buf.append(ch)

            if quote_char is not None:
                return None

            tail = "".join(buf).strip()
            if tail:
                param_items.append(tail)

            if not param_items:
                return None

            parameters: Dict[str, str] = {}
            for param_item in param_items:
                if "=" in param_item:
                    key, val = param_item.split("=", 1)
                    key = key.strip()
                    val = val.strip()
                    if len(val) >= 2:
                        if (val[0] == '"' and val[-1] == '"') or (val[0] == "'" and val[-1] == "'"):
                            val = val[1:-1]
                else:
                    key = param_item.strip()
                    val = "true"

                if not key:
                    return None

                if allowed_normalized and key.lower() not in allowed_normalized:
                    return None

                parameters[key] = val

            return parameters

        def split_base_and_params(value_str: str) -> tuple[str, str | None]:
            stripped = value_str.rstrip()
            if not stripped.endswith(")"):
                return value_str.strip(), None

            depth = 0
            open_idx: int | None = None
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
                return value_str.strip(), None

            candidate_base = stripped[:open_idx].rstrip()
            params_section = stripped[open_idx + 1 : -1].strip()

            if not candidate_base:
                return value_str.strip(), None

            return candidate_base, params_section

        # Support parameter-only values like "(variable=foo)" when allowed.
        if value.startswith("(") and value.endswith(")") and allowed_normalized is not None:
            params_section = value[1:-1].strip()
            parsed = parse_parameters(params_section) if params_section else None
            if parsed:
                return "", parsed

        # Handle quoted or Obsidian-style paths up front and leave any trailing
        # parentheses to be treated as parameters on the remainder.
        base_value: str | None = None
        remainder = value
        if remainder.startswith("[["):
            close_idx = remainder.find("]]")
            if close_idx != -1:
                base_value = remainder[2:close_idx]
                remainder = remainder[close_idx + 2 :].strip()
        elif remainder.startswith('"') or remainder.startswith("'"):
            quote_char = remainder[0]
            close_idx = remainder.find(quote_char, 1)
            if close_idx != -1:
                base_value = remainder[1:close_idx]
                remainder = remainder[close_idx + 1 :].strip()

        parameters: Dict[str, str] = {}

        # If we already extracted a base path (quoted or [[link]]), only parse
        # parameters from the remaining text.
        if base_value is not None:
            if remainder:
                stripped_remainder = remainder.strip()

                if (
                    stripped_remainder.startswith("(")
                    and stripped_remainder.endswith(")")
                ):
                    params_section = stripped_remainder[1:-1].strip()
                else:
                    _, params_section = split_base_and_params(remainder)

                parsed = parse_parameters(params_section) if params_section else None
                if parsed:
                    parameters = parsed
            return base_value, parameters

        # Otherwise, attempt to split trailing parameters from the value. If the
        # trailing parentheses don't parse as recognized parameters, treat the
        # whole string as the base value to avoid misclassifying filenames.
        candidate_base, params_section = split_base_and_params(remainder)
        parsed_params = parse_parameters(params_section) if params_section else None

        if parsed_params is None:
            return value, {}

        return candidate_base, parsed_params
