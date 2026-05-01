"""Workflow execution policy built on the process-local task coordinator."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Literal

from core.authoring.workflow_execution import WorkflowExecutionResult, execute_workflow_by_id
from core.logger import UnifiedLogger
from core.settings import get_workflow_task_timeout_seconds

from .execution_tasks import TaskCoordinator


WorkflowSource = Literal["scheduler", "api", "tool", "system"]


class WorkflowGovernor:
    """Coordinate workflow execution lanes and shared workflow task policy."""

    def __init__(
        self,
        *,
        task_coordinator: TaskCoordinator,
        logger: UnifiedLogger | None = None,
    ) -> None:
        self._task_coordinator = task_coordinator
        self._logger = logger or UnifiedLogger(tag="workflow-governor")
        self._lane_guard = asyncio.Lock()
        self._lane_locks: dict[str, asyncio.Lock] = {}

    async def execute_workflow(
        self,
        *,
        global_id: str,
        source: WorkflowSource,
        step_name: str | None = None,
        expect_failure: bool = False,
        include_load_errors: bool = False,
    ) -> WorkflowExecutionResult:
        """Execute one workflow if its vault lane is available."""
        vault_name = self._split_vault_name(global_id)
        lane_lock = await self._get_lane_lock(vault_name)
        if lane_lock.locked():
            reason = f"workflow_vault_active:{vault_name}"
            self._logger.add_sink("validation").info(
                "workflow_task_overlap_skipped",
                data={
                    "event": "workflow_task_overlap_skipped",
                    "workflow_id": global_id,
                    "vault": vault_name,
                    "source": source,
                    "reason": reason,
                },
            )
            return WorkflowExecutionResult(
                success=True,
                global_id=global_id,
                status="skipped",
                execution_time_seconds=0.0,
                output_files=[],
                reason=reason,
                details=[],
                message=f"Workflow '{global_id}' skipped: {reason}",
            )

        await lane_lock.acquire()
        task_id = ""
        try:
            async with self._task_coordinator.track_current_task(
                kind="workflow",
                scope=f"workflow_vault:{vault_name}",
                source=source,
                label=global_id,
                metadata={
                    "workflow_id": global_id,
                    "vault": vault_name,
                    "step_name": step_name,
                },
            ) as task:
                task_id = task.task_id
                self._log_workflow_event(
                    "workflow_task_started",
                    global_id=global_id,
                    vault_name=vault_name,
                    source=source,
                    task_id=task_id,
                )
                timeout = get_workflow_task_timeout_seconds()
                try:
                    if timeout > 0:
                        result = await asyncio.wait_for(
                            execute_workflow_by_id(
                                global_id,
                                step_name=step_name,
                                expect_failure=expect_failure,
                                include_load_errors=include_load_errors,
                            ),
                            timeout=timeout,
                        )
                    else:
                        result = await execute_workflow_by_id(
                            global_id,
                            step_name=step_name,
                            expect_failure=expect_failure,
                            include_load_errors=include_load_errors,
                        )
                except TimeoutError:
                    reason = f"workflow_task_timeout:{timeout:g}s"
                    await self._task_coordinator.mark_timed_out(task_id, reason=reason)
                    self._log_workflow_event(
                        "workflow_task_timed_out",
                        global_id=global_id,
                        vault_name=vault_name,
                        source=source,
                        task_id=task_id,
                        status="timed_out",
                        reason=reason,
                    )
                    return WorkflowExecutionResult(
                        success=False,
                        global_id=global_id,
                        status="timed_out",
                        execution_time_seconds=timeout,
                        output_files=[],
                        reason=reason,
                        details=[],
                        message=f"Workflow '{global_id}' timed out after {timeout:g} seconds",
                    )

                result = replace(result, details=[*result.details, f"task_id: {task_id}"])
                self._log_workflow_event(
                    "workflow_task_completed",
                    global_id=global_id,
                    vault_name=vault_name,
                    source=source,
                    task_id=task_id,
                    status=result.status,
                    reason=result.reason,
                )
                return result
        except asyncio.CancelledError:
            self._log_workflow_event(
                "workflow_task_cancelled",
                global_id=global_id,
                vault_name=vault_name,
                source=source,
                task_id=task_id,
                status="cancelled",
                reason="cancelled",
            )
            raise
        except Exception as exc:
            self._log_workflow_event(
                "workflow_task_failed",
                global_id=global_id,
                vault_name=vault_name,
                source=source,
                task_id=task_id,
                status="failed",
                reason=f"{type(exc).__name__}: {exc}",
            )
            raise
        finally:
            lane_lock.release()

    async def _get_lane_lock(self, vault_name: str) -> asyncio.Lock:
        async with self._lane_guard:
            lock = self._lane_locks.get(vault_name)
            if lock is None:
                lock = asyncio.Lock()
                self._lane_locks[vault_name] = lock
            return lock

    def _log_workflow_event(
        self,
        event: str,
        *,
        global_id: str,
        vault_name: str,
        source: str,
        task_id: str,
        status: str | None = None,
        reason: str | None = None,
    ) -> None:
        self._logger.add_sink("validation").info(
            event,
            data={
                "event": event,
                "workflow_id": global_id,
                "vault": vault_name,
                "source": source,
                "task_id": task_id,
                "status": status,
                "reason": reason,
            },
        )

    @staticmethod
    def _split_vault_name(global_id: str) -> str:
        if "/" not in global_id:
            raise ValueError(f"Invalid global_id format. Expected 'vault/name', got: {global_id}")
        vault_name, _workflow_name = global_id.split("/", 1)
        return vault_name
