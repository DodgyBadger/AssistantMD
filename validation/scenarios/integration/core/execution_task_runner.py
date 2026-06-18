"""Validate the generic execution task runner shell."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from core.runtime.execution_tasks import ExecutionTaskKind, ExecutionTaskSource
from core.runtime.task_runner import ExecutionTaskHooks, ExecutionTaskSpec
from validation.core.base_scenario import BaseScenario


class ExecutionTaskRunnerScenario(BaseScenario):
    """Validate background runner task creation, cancellation, and failure."""

    async def test_scenario(self):
        self.create_vault("ExecutionTaskRunnerVault")
        await self.start_system()
        runtime = self._runtime()

        completed_task = await runtime.task_runner.start_background(
            ExecutionTaskSpec(
                kind=ExecutionTaskKind.CHAT,
                scope="runner:completed",
                source=ExecutionTaskSource.SYSTEM,
                label="runner-completed",
                metadata={"probe": "completed"},
            ),
            _complete_task,
        )
        completed = await self._wait_for_task_terminal(completed_task.task_id)
        self.soft_assert_equal(
            completed.status if completed else None,
            "completed",
            "Runner should mark successful background work completed",
        )
        self.soft_assert_equal(
            completed.started_at is not None if completed else False,
            True,
            "Runner should mark successful background work started",
        )

        cancel_hook_task_ids: list[str] = []
        cancel_started = asyncio.Event()
        cancelled_task = await runtime.task_runner.start_background(
            ExecutionTaskSpec(
                kind=ExecutionTaskKind.CHAT,
                scope="runner:cancelled",
                source=ExecutionTaskSource.SYSTEM,
                label="runner-cancelled",
                metadata={"probe": "cancelled"},
            ),
            lambda task: _wait_until_cancelled(task, cancel_started),
            hooks=ExecutionTaskHooks(
                on_cancelled=lambda task_id: _record_task_id(cancel_hook_task_ids, task_id),
            ),
        )
        await asyncio.wait_for(cancel_started.wait(), timeout=2.0)
        await runtime.task_coordinator.cancel_task(cancelled_task.task_id, reason="validation_cancel")
        cancelled = await self._wait_for_task_terminal(cancelled_task.task_id)
        self.soft_assert_equal(
            cancelled.status if cancelled else None,
            "cancelled",
            "Runner should mark cancelled background work cancelled",
        )
        self.soft_assert_equal(
            cancel_hook_task_ids,
            [cancelled_task.task_id],
            "Runner should call cancellation hook exactly once",
        )

        failure_hook: list[tuple[str, str]] = []
        failed_task = await runtime.task_runner.start_background(
            ExecutionTaskSpec(
                kind=ExecutionTaskKind.CHAT,
                scope="runner:failed",
                source=ExecutionTaskSource.SYSTEM,
                label="runner-failed",
                metadata={"probe": "failed"},
            ),
            _fail_task,
            hooks=ExecutionTaskHooks(
                on_failed=lambda task_id, exc: _record_failure(failure_hook, task_id, exc),
            ),
        )
        failed = await self._wait_for_task_terminal(failed_task.task_id)
        self.soft_assert_equal(
            failed.status if failed else None,
            "failed",
            "Runner should mark failed background work failed",
        )
        self.soft_assert_equal(
            failed.terminal_reason if failed else "",
            "RuntimeError: forced runner failure",
            "Runner should preserve failure reason from TaskCoordinator",
        )
        self.soft_assert_equal(
            failure_hook,
            [(failed_task.task_id, "RuntimeError")],
            "Runner should call failure hook with the original exception",
        )

        await self.stop_system()
        self.teardown_scenario()
        self.assert_no_failures()

    async def _wait_for_task_terminal(self, task_id: str):
        runtime = self._runtime()
        for _ in range(100):
            task = await runtime.task_coordinator.get_task(task_id)
            if task is not None and task.is_terminal:
                return task
            await asyncio.sleep(0.02)
        return None

    def _runtime(self):
        from core.runtime.state import get_runtime_context

        return get_runtime_context()


async def _complete_task(_task) -> None:
    await asyncio.sleep(0)


async def _wait_until_cancelled(_task, started: asyncio.Event) -> None:
    started.set()
    await asyncio.Event().wait()


async def _fail_task(_task) -> None:
    raise RuntimeError("forced runner failure")


async def _record_task_id(task_ids: list[str], task_id: str) -> None:
    task_ids.append(task_id)


async def _record_failure(
    failures: list[tuple[str, str]],
    task_id: str,
    exc: BaseException,
) -> None:
    failures.append((task_id, type(exc).__name__))
