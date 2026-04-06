"""
Cache directive parsing for reusable outputs.
"""

from __future__ import annotations

from typing import Dict, Any

from core.context.cache_semantics import parse_cache_mode_value
from .base import DirectiveProcessor
from .parser import DirectiveValueParser


def _parse_cache_value(value: str) -> Dict[str, Any]:
    if DirectiveValueParser.is_empty(value):
        raise ValueError("Value cannot be empty")

    normalized = DirectiveValueParser.normalize_string(value, to_lower=True)
    return parse_cache_mode_value(normalized)


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
