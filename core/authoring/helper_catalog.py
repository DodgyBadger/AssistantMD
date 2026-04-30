"""Default Monty helper catalog for the authoring runtime."""

from __future__ import annotations

from core.authoring.helpers import get_builtin_helper_definitions
from core.authoring.registry import AuthoringCapabilityRegistry


def create_builtin_registry() -> AuthoringCapabilityRegistry:
    """Build the default built-in capability registry."""
    registry = AuthoringCapabilityRegistry()
    registry.register_many(get_builtin_helper_definitions())
    return registry
