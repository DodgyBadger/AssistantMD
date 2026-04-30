"""Shared thinking/reasoning configuration helpers."""

from __future__ import annotations

from typing import Any, Literal, TypeAlias


ThinkingEffort: TypeAlias = Literal["minimal", "low", "medium", "high", "xhigh"]
ThinkingValue: TypeAlias = bool | ThinkingEffort | None

_THINKING_EFFORTS: set[str] = {"minimal", "low", "medium", "high", "xhigh"}
_TRUE_VALUES: set[str] = {"true", "1", "yes", "on"}
_FALSE_VALUES: set[str] = {"false", "0", "no", "off"}
_DEFAULT_VALUES: set[str] = {"", "default", "provider_default", "inherit", "null", "none"}


def normalize_thinking_value(raw_value: Any, *, source_name: str = "thinking") -> ThinkingValue:
    """Normalize a user/config provided thinking value."""
    if raw_value is None:
        return None
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in _DEFAULT_VALUES:
            return None
        if normalized in _TRUE_VALUES:
            return True
        if normalized in _FALSE_VALUES:
            return False
        if normalized in _THINKING_EFFORTS:
            return normalized  # type: ignore[return-value]

    raise ValueError(
        f"{source_name} must be one of: default, on, off, minimal, low, medium, high, xhigh"
    )


def thinking_value_to_label(value: ThinkingValue) -> str:
    """Convert a normalized thinking value into a stable event/config label."""
    if value is None:
        return "default"
    if value is True:
        return "on"
    if value is False:
        return "off"
    return value

