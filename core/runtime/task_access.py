"""Authority-mediated access to process-local execution tasks."""

from __future__ import annotations

from core.identity import AuthorizationService, require_current_execution_authority

from .execution_tasks import (
    ExecutionTaskCancellationResult,
    ExecutionTaskSnapshot,
    TaskCoordinator,
)


class ExecutionTaskAccessService:
    """Expose task reads and cancellation under the active authority."""

    def __init__(
        self,
        coordinator: TaskCoordinator,
        authorization: AuthorizationService,
    ) -> None:
        self._coordinator = coordinator
        self._authorization = authorization

    async def get_task(self, task_id: str) -> ExecutionTaskSnapshot | None:
        """Return an accessible task, concealing tasks owned by other principals."""
        authority = require_current_execution_authority()
        snapshot = await self._coordinator.get_task(task_id)
        if snapshot is None:
            return None
        if not self._authorization.can_access_execution_task(authority, snapshot):
            return None
        return snapshot

    async def list_tasks(
        self,
        *,
        kind: str | None = None,
        scope: str | None = None,
        include_terminal: bool = True,
    ) -> list[ExecutionTaskSnapshot]:
        """Return only tasks accessible to the active authority."""
        authority = require_current_execution_authority()
        snapshots = await self._coordinator.list_tasks(
            kind=kind,
            scope=scope,
            include_terminal=include_terminal,
        )
        return [
            snapshot
            for snapshot in snapshots
            if self._authorization.can_access_execution_task(authority, snapshot)
        ]

    async def cancel_task(
        self,
        task_id: str,
        *,
        reason: str = "cancel_requested",
    ) -> ExecutionTaskCancellationResult | None:
        """Cancel an accessible task, concealing tasks owned by other principals."""
        if await self.get_task(task_id) is None:
            return None
        return await self._coordinator.cancel_task(task_id, reason=reason)
