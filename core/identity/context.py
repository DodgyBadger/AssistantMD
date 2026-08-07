"""Context-local execution authority propagation."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from .models import ExecutionAuthority

_CURRENT_EXECUTION_AUTHORITY: ContextVar[ExecutionAuthority | None] = ContextVar(
    "current_execution_authority",
    default=None,
)


def get_current_execution_authority() -> ExecutionAuthority | None:
    """Return authority for the current execution context, if present."""
    return _CURRENT_EXECUTION_AUTHORITY.get()


def require_current_execution_authority() -> ExecutionAuthority:
    """Return current authority or fail at an unowned execution boundary."""
    authority = get_current_execution_authority()
    if authority is None:
        raise RuntimeError("Execution authority is required for this operation.")
    return authority


@contextmanager
def use_execution_authority(
    authority: ExecutionAuthority,
) -> Iterator[ExecutionAuthority]:
    """Install execution authority for nested work and reset it reliably."""
    token = _CURRENT_EXECUTION_AUTHORITY.set(authority)
    try:
        yield authority
    finally:
        _CURRENT_EXECUTION_AUTHORITY.reset(token)
