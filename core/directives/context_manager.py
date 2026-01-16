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
    """Processor for @recent-runs directive."""

    def get_directive_name(self) -> str:
        return "recent-runs"

    def validate_value(self, value: str) -> bool:
        try:
            _parse_non_negative_int(value)
            return True
        except ValueError:
            return False

    def process_value(self, value: str, vault_path: str, **context) -> int:
        return _parse_non_negative_int(value)


class PassthroughRunsDirective(DirectiveProcessor):
    """Processor for @passthrough-runs directive."""

    def get_directive_name(self) -> str:
        return "passthrough-runs"

    def validate_value(self, value: str) -> bool:
        try:
            _parse_passthrough_runs(value)
            return True
        except ValueError:
            return False

    def process_value(self, value: str, vault_path: str, **context) -> int:
        return _parse_passthrough_runs(value)


class TokenThresholdDirective(DirectiveProcessor):
    """Processor for @token-threshold directive."""

    def get_directive_name(self) -> str:
        return "token-threshold"

    def validate_value(self, value: str) -> bool:
        try:
            _parse_non_negative_int(value)
            return True
        except ValueError:
            return False

    def process_value(self, value: str, vault_path: str, **context) -> int:
        return _parse_non_negative_int(value)


class RecentSummariesDirective(DirectiveProcessor):
    """Processor for @recent-summaries directive."""

    def get_directive_name(self) -> str:
        return "recent-summaries"

    def validate_value(self, value: str) -> bool:
        try:
            _parse_non_negative_int(value)
            return True
        except ValueError:
            return False

    def process_value(self, value: str, vault_path: str, **context) -> int:
        return _parse_non_negative_int(value)
