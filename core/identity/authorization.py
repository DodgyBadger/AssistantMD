"""Central authorization checks for principal-owned runtime resources."""

from __future__ import annotations

from typing import Protocol

from .models import Principal


class PrincipalOwned(Protocol):
    """Minimal shape for a durable principal-owned resource."""

    @property
    def owner_principal_id(self) -> str:
        """Stable owner principal ID."""
        ...


class PrincipalTask(Protocol):
    """Minimal shape for a principal-owned execution task."""

    @property
    def principal_id(self) -> str:
        """Captured execution principal ID."""
        ...


class AuthorizationError(PermissionError):
    """Raised when a principal cannot access a protected resource."""


def require_session_access(principal: Principal, session: PrincipalOwned) -> None:
    """Require access to a principal-owned chat session."""
    if session.owner_principal_id != principal.principal_id:
        raise AuthorizationError("The principal cannot access this chat session.")


def require_execution_task_access(principal: Principal, task: PrincipalTask) -> None:
    """Require access to a principal-owned execution task."""
    if task.principal_id != principal.principal_id:
        raise AuthorizationError("The principal cannot access this execution task.")
