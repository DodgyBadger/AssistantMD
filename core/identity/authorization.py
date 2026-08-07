"""Central authorization checks for principal-owned runtime resources."""

from __future__ import annotations

from typing import Protocol

from .models import LOCAL_USER_PRINCIPAL_ID


class PrincipalIdentity(Protocol):
    """Minimal identity shape accepted by authorization policy."""

    @property
    def principal_id(self) -> str:
        """Stable principal ID."""
        ...


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


class AuthorizationService:
    """Central policy for principal-owned runtime resources."""

    def can_access_session(
        self,
        principal: PrincipalIdentity,
        session: PrincipalOwned,
    ) -> bool:
        """Return whether a principal may access one chat session."""
        return session.owner_principal_id == principal.principal_id

    def require_session_access(
        self,
        principal: PrincipalIdentity,
        session: PrincipalOwned,
    ) -> None:
        """Require access to a principal-owned chat session."""
        if not self.can_access_session(principal, session):
            raise AuthorizationError("The principal cannot access this chat session.")

    def can_access_execution_task(
        self,
        principal: PrincipalIdentity,
        task: PrincipalTask,
    ) -> bool:
        """Return whether a principal may access one execution task."""
        return (
            principal.principal_id == LOCAL_USER_PRINCIPAL_ID
            or task.principal_id == principal.principal_id
        )

    def require_execution_task_access(
        self,
        principal: PrincipalIdentity,
        task: PrincipalTask,
    ) -> None:
        """Require access to a principal-owned execution task."""
        if not self.can_access_execution_task(principal, task):
            raise AuthorizationError("The principal cannot access this execution task.")


_DEFAULT_AUTHORIZATION_SERVICE = AuthorizationService()


def require_session_access(
    principal: PrincipalIdentity,
    session: PrincipalOwned,
) -> None:
    """Require access using the default authorization policy."""
    _DEFAULT_AUTHORIZATION_SERVICE.require_session_access(principal, session)


def require_execution_task_access(
    principal: PrincipalIdentity,
    task: PrincipalTask,
) -> None:
    """Require access using the default authorization policy."""
    _DEFAULT_AUTHORIZATION_SERVICE.require_execution_task_access(principal, task)
