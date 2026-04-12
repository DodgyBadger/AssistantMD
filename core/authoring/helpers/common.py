"""Shared helper-definition utilities for the Monty authoring runtime."""

from __future__ import annotations

from typing import Any

from core.authoring.contracts import (
    BUILTIN_CAPABILITY_NAMES,
    AuthoringCapabilityDefinition,
)


def build_capability(
    *,
    name: str,
    doc: str,
    contract: dict[str, Any],
    handler: Any,
) -> AuthoringCapabilityDefinition:
    """Build one helper definition."""
    if name not in BUILTIN_CAPABILITY_NAMES:
        raise ValueError(f"Unknown built-in capability '{name}'")
    return AuthoringCapabilityDefinition(
        name=name,
        doc=doc,
        handler=handler,
        contract=contract,
    )


def placeholder_contract(name: str, signature: str) -> dict[str, Any]:
    """Build a minimal contract stub for an unfinished helper."""
    return {
        "signature": signature,
        "summary": f"Experimental built-in capability '{name}'.",
        "types": {},
        "return_shape": {},
        "examples": [],
    }
