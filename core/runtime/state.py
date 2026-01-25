"""
Global runtime context state management.

Provides singleton access to runtime context with explicit teardown
for test isolation and clean lifecycle management.
"""

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .context import RuntimeContext


# Global runtime context instance
_runtime_context: Optional["RuntimeContext"] = None
_runtime_boot_counter = 0


def set_runtime_context(context: Optional["RuntimeContext"]) -> None:
    """
    Set the global runtime context.

    Allows explicit teardown by passing None, enabling test isolation
    and clean shutdown semantics. Only one context can be active at a time.

    Args:
        context: RuntimeContext instance or None to clear

    Raises:
        RuntimeStateError: If attempting to set context when one already exists
    """
    global _runtime_context

    if context is not None and _runtime_context is not None:
        raise RuntimeStateError(
            "Runtime context already exists. Call set_runtime_context(None) "
            "to clear existing context before setting a new one."
        )

    _runtime_context = context


def get_runtime_context() -> "RuntimeContext":
    """
    Get the current runtime context.

    Provides access to scheduler, assistant loader, and other core services
    without requiring imports from main or other modules.

    Returns:
        Current RuntimeContext instance

    Raises:
        RuntimeStateError: If no runtime context is available
    """
    if _runtime_context is None:
        raise RuntimeStateError(
            "No runtime context available. Ensure bootstrap_runtime() "
            "has been called before accessing runtime services."
        )

    return _runtime_context


def has_runtime_context() -> bool:
    """
    Check if a runtime context is currently available.

    Returns:
        True if context is available, False otherwise
    """
    return _runtime_context is not None


def clear_runtime_context() -> None:
    """
    Clear the current runtime context.

    Convenience method equivalent to set_runtime_context(None).
    Useful for cleanup and test teardown.
    """
    set_runtime_context(None)


def next_boot_id() -> int:
    """Return the next runtime boot sequence number."""
    global _runtime_boot_counter
    _runtime_boot_counter += 1
    return _runtime_boot_counter


class RuntimeStateError(Exception):
    """Raised when runtime context state is invalid or unavailable."""
    pass
