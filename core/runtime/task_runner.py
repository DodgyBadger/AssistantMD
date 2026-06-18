"""Generic runtime execution task runner shell."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from core.runtime.background import RuntimeBackgroundSpawner
from core.runtime.execution_tasks import ExecutionTaskSnapshot, TaskCoordinator


@dataclass(frozen=True)
class ExecutionTaskSpec:
    """Identity and metadata for one runtime execution task."""

    kind: str
    scope: str
    source: str
    label: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionTaskHooks:
    """Optional domain hooks around generic execution task lifecycle."""

    on_cancelled: Callable[[str], Awaitable[None]] | None = None
    on_failed: Callable[[str, BaseException], Awaitable[None]] | None = None


class ExecutionTaskRunner:
    """Create, attach, and run background execution tasks."""

    def __init__(
        self,
        *,
        task_coordinator: TaskCoordinator,
        background_spawner: RuntimeBackgroundSpawner,
    ) -> None:
        self._task_coordinator = task_coordinator
        self._background_spawner = background_spawner

    async def start_background(
        self,
        spec: ExecutionTaskSpec,
        run: Callable[[ExecutionTaskSnapshot], Awaitable[Any]],
        *,
        hooks: ExecutionTaskHooks | None = None,
        start_immediately: bool = True,
    ) -> ExecutionTaskSnapshot:
        """Create a queued task and run it in the runtime background."""
        task = await self._task_coordinator.create_queued_task(
            kind=spec.kind,
            scope=spec.scope,
            source=spec.source,
            label=spec.label,
            metadata=spec.metadata,
        )

        async def _run() -> None:
            try:
                async with self._task_coordinator.track_existing_task(task.task_id) as tracked_task:
                    if start_immediately:
                        await self._task_coordinator.mark_started(tracked_task.task_id)
                    await run(tracked_task)
            except asyncio.CancelledError:
                await self._call_cancelled_hook(hooks, task.task_id)
                raise
            except Exception as exc:  # noqa: BLE001 - task status is recorded by coordinator
                if await self._task_has_cancelled(task.task_id):
                    await self._call_cancelled_hook(hooks, task.task_id)
                    return
                await self._call_failed_hook(hooks, task.task_id, exc)
                return

        self._background_spawner.spawn(_run)
        return task

    async def _task_has_cancelled(self, task_id: str) -> bool:
        snapshot = await self._task_coordinator.get_task(task_id)
        if snapshot is None:
            return True
        return snapshot.status == "cancelled" or snapshot.cancel_requested

    @staticmethod
    async def _call_cancelled_hook(hooks: ExecutionTaskHooks | None, task_id: str) -> None:
        if hooks is not None and hooks.on_cancelled is not None:
            await hooks.on_cancelled(task_id)

    @staticmethod
    async def _call_failed_hook(
        hooks: ExecutionTaskHooks | None,
        task_id: str,
        exc: BaseException,
    ) -> None:
        if hooks is not None and hooks.on_failed is not None:
            await hooks.on_failed(task_id, exc)
