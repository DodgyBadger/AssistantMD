"""
Cache directive parsing for reusable outputs.
"""

from __future__ import annotations

import re
from typing import Dict, Any

from .base import DirectiveProcessor
from .parser import DirectiveValueParser


_DURATION_PATTERN = re.compile(r"^(?P<amount>\d+)\s*(?P<unit>[smhd])$")
_UNIT_SECONDS = {
    "s": 1,
    "m": 60,
    "h": 60 * 60,
    "d": 60 * 60 * 24,
}
_NAMED_MODES = {"daily", "weekly", "session"}


def _parse_cache_value(value: str) -> Dict[str, Any]:
    if DirectiveValueParser.is_empty(value):
        raise ValueError("Value cannot be empty")

    normalized = DirectiveValueParser.normalize_string(value, to_lower=True)
    if normalized in _NAMED_MODES:
        return {"mode": normalized}

    match = _DURATION_PATTERN.match(normalized)
    if not match:
        raise ValueError(
            "Expected duration like 10m/24h/1d or one of: daily, weekly, session"
        )

    amount = int(match.group("amount"))
    if amount <= 0:
        raise ValueError("Duration must be greater than 0")

    unit = match.group("unit")
    ttl_seconds = amount * _UNIT_SECONDS[unit]
    return {"mode": "duration", "ttl_seconds": ttl_seconds}


class CacheDirective(DirectiveProcessor):
    """Processor for @cache directive."""

    def get_directive_name(self) -> str:
        return "cache"

    def validate_value(self, value: str) -> bool:
        try:
            _parse_cache_value(value)
            return True
        except ValueError:
            return False

    def process_value(self, value: str, vault_path: str, **context) -> Dict[str, Any]:
        return _parse_cache_value(value)
