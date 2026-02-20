"""
Context manager override directives.
"""

from __future__ import annotations

from .base import DirectiveProcessor
from .parser import DirectiveValueParser


def _parse_non_negative_int(value: str) -> int:
    if DirectiveValueParser.is_empty(value):
        raise ValueError("Value cannot be empty")

    try:
        parsed = int(value.strip())
    except ValueError as exc:
        raise ValueError(f"Expected an integer value, got '{value}'") from exc

    if parsed < 0:
        raise ValueError("Value must be >= 0")

    return parsed


def _parse_non_negative_int_or_all(value: str) -> int:
    if DirectiveValueParser.is_empty(value):
        raise ValueError("Value cannot be empty")

    normalized = value.strip().lower()
    if normalized == "all":
        return -1

    return _parse_non_negative_int(normalized)


def _parse_passthrough_runs(value: str) -> int:
    if DirectiveValueParser.is_empty(value):
        raise ValueError("Value cannot be empty")

    normalized = value.strip().lower()
    if normalized == "all":
        return -1

    try:
        parsed = int(normalized)
    except ValueError as exc:
        raise ValueError(f"Expected an integer value or 'all', got '{value}'") from exc

    if parsed < -1:
        raise ValueError("Value must be -1 or >= 0")

    return parsed


class RecentRunsDirective(DirectiveProcessor):
    """Processor for @recent_runs directive."""

    def get_directive_name(self) -> str:
        return "recent_runs"

    def validate_value(self, value: str) -> bool:
        try:
            _parse_non_negative_int_or_all(value)
            return True
        except ValueError:
            return False

    def process_value(self, value: str, vault_path: str, **context) -> int:
        return _parse_non_negative_int_or_all(value)


class PassthroughRunsDirective(DirectiveProcessor):
    """Processor for @passthrough_runs directive."""

    def get_directive_name(self) -> str:
        return "passthrough_runs"

    def validate_value(self, value: str) -> bool:
        try:
            _parse_passthrough_runs(value)
            return True
        except ValueError:
            return False

    def process_value(self, value: str, vault_path: str, **context) -> int:
        return _parse_passthrough_runs(value)


class RecentSummariesDirective(DirectiveProcessor):
    """Processor for @recent_summaries directive."""

    def get_directive_name(self) -> str:
        return "recent_summaries"

    def validate_value(self, value: str) -> bool:
        try:
            _parse_non_negative_int_or_all(value)
            return True
        except ValueError:
            return False

    def process_value(self, value: str, vault_path: str, **context) -> int:
        return _parse_non_negative_int_or_all(value)
