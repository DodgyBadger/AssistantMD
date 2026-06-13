"""Workflow execution policy built on the process-local task coordinator."""

from __future__ import annotations

import asyncio
import contextvars
from dataclasses import replace
from typing import Any

from core.authoring.workflow_execution import WorkflowExecutionResult, execute_workflow_by_id
from core.logger import UnifiedLogger
from core.settings import get_max_concurrent_workflows, get_workflow_task_timeout_seconds
from core.tools.failures import FailureClassification, classify_exception

from .execution_tasks import (
    ExecutionTaskKind,
    ExecutionTaskSnapshot,
    ExecutionTaskSource,
    ExecutionTaskStatus,
    TaskCoordinator,
    workflow_vault_scope,
)


WorkflowSource = ExecutionTaskSource


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
        self._global_limit_guard = asyncio.Lock()
        self._global_limit = 0
        self._global_semaphore: asyncio.Semaphore | None = None

    async def execute_workflow(
        self,
        *,
        global_id: str,
        source: WorkflowSource,
        step_name: str | None = None,
        expect_failure: bool = False,
        include_load_errors: bool = False,
        task_id: str | None = None,
    ) -> WorkflowExecutionResult:
        """Execute one workflow after waiting for its vault and global lanes."""
        vault_name, workflow_name = self._split_workflow_identity(global_id)
        source_value = str(source)
        active_task_id = task_id or ""
        task_context = (
            self._task_coordinator.track_existing_task(task_id)
            if task_id
            else self._task_coordinator.track_current_task(
                kind=ExecutionTaskKind.WORKFLOW,
                scope=workflow_vault_scope(vault_name),
                source=source,
                label=global_id,
                metadata={
                    "workflow_id": global_id,
                    "vault": vault_name,
                    "step_name": step_name,
                },
                start_immediately=False,
            )
        )
        async with task_context as task:
            lane_lock = await self._get_lane_lock(vault_name)
            if lane_lock.locked():
                await self._task_coordinator.heartbeat(
                    task.task_id,
                    status="queued_for_vault",
                    metadata={
                        "workflow_queue_reason": f"workflow_vault_active:{vault_name}",
                    },
                )
                self._log_queue_event(
                    "workflow_task_queued_for_vault",
                    global_id=global_id,
                    vault_name=vault_name,
                    workflow_name=workflow_name,
                    source=source_value,
                    task_id=task.task_id,
                    reason=f"workflow_vault_active:{vault_name}",
                )

            await lane_lock.acquire()
            global_semaphore: asyncio.Semaphore | None = None
            global_permit_acquired = False
            active_task_id = task.task_id
            try:
                global_semaphore = await self._get_global_semaphore()
                if global_semaphore is not None:
                    if global_semaphore.locked():
                        await self._task_coordinator.heartbeat(
                            active_task_id,
                            status="queued_for_global_capacity",
                            metadata={
                                "workflow_queue_reason": "workflow_global_capacity_active",
                            },
                        )
                        self._log_queue_event(
                            "workflow_task_queued_for_global_capacity",
                            global_id=global_id,
                            vault_name=vault_name,
                            workflow_name=workflow_name,
                            source=source_value,
                            task_id=active_task_id,
                            reason="workflow_global_capacity_active",
                        )
                    await global_semaphore.acquire()
                    global_permit_acquired = True

                await self._task_coordinator.mark_started(active_task_id)
                await self._task_coordinator.heartbeat(
                    active_task_id,
                    status="workflow_running",
                    metadata={
                        "workflow_queue_reason": None,
                        "workflow_id": global_id,
                        "workflow_name": workflow_name,
                        "vault": vault_name,
                        "step_name": step_name,
                    },
                )
                active_task_id = task.task_id
                self._log_workflow_event(
                    "workflow_task_started",
                    global_id=global_id,
                    vault_name=vault_name,
                    workflow_name=workflow_name,
                    source=source_value,
                    task_id=active_task_id,
                    step_name=step_name,
                    expect_failure=expect_failure,
                    include_load_errors=include_load_errors,
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
                    timeout_classification = FailureClassification(
                        error_type="TimeoutError",
                        failure_kind="workflow_timeout",
                        retryable=False,
                        phase="workflow_execution",
                        message=reason,
                        suggested_action=(
                            "Do not retry the same broad workflow unchanged. Narrow the workflow scope, "
                            "split the batch, or increase the workflow timeout if the scope is intentional."
                        ),
                    )
                    timeout_result = WorkflowExecutionResult(
                        success=False,
                        global_id=global_id,
                        status="timed_out",
                        execution_time_seconds=timeout,
                        output_files=[],
                        reason=reason,
                        details=[],
                        message=f"Workflow '{global_id}' timed out after {timeout:g} seconds",
                    )
                    await self._task_coordinator.update_metadata(
                        active_task_id,
                        {
                            "workflow_result": timeout_result.to_dict(),
                            "workflow_failure": _build_workflow_failure_metadata(
                                global_id=global_id,
                                vault_name=vault_name,
                                workflow_name=workflow_name,
                                step_name=step_name,
                                source=source_value,
                                status="timed_out",
                                reason=reason,
                                classification=timeout_classification,
                                output_files=[],
                                message=timeout_result.message,
                            ),
                        },
                    )
                    await self._task_coordinator.mark_timed_out(active_task_id, reason=reason)
                    self._log_workflow_event(
                        "workflow_task_timed_out",
                        global_id=global_id,
                        vault_name=vault_name,
                        workflow_name=workflow_name,
                        source=source_value,
                        task_id=active_task_id,
                        status="timed_out",
                        reason=reason,
                        step_name=step_name,
                        expect_failure=expect_failure,
                        include_load_errors=include_load_errors,
                        execution_time_seconds=timeout,
                        output_files=[],
                        message=timeout_result.message,
                        failure_kind=timeout_classification.failure_kind,
                        retryable=timeout_classification.retryable,
                    )
                    return timeout_result

                result = replace(result, details=[*result.details, f"task_id: {active_task_id}"])
                await self._task_coordinator.update_metadata(
                    active_task_id,
                    {"workflow_result": result.to_dict()},
                )
                self._log_workflow_event(
                    "workflow_task_completed",
                    global_id=global_id,
                    vault_name=vault_name,
                    workflow_name=workflow_name,
                    source=source_value,
                    task_id=active_task_id,
                    status=result.status,
                    reason=result.reason,
                    step_name=step_name,
                    expect_failure=expect_failure,
                    include_load_errors=include_load_errors,
                    execution_time_seconds=result.execution_time_seconds,
                    output_files=result.output_files,
                    message=result.message,
                )
                if str(result.status or "").strip().lower() == ExecutionTaskStatus.FAILED.value:
                    await self._task_coordinator.update_metadata(
                        active_task_id,
                        {
                            "workflow_failure": _build_workflow_failure_metadata(
                                global_id=global_id,
                                vault_name=vault_name,
                                workflow_name=workflow_name,
                                step_name=step_name,
                                source=source_value,
                                status=result.status,
                                reason=result.reason,
                                classification=FailureClassification(
                                    error_type="WorkflowFailed",
                                    failure_kind="workflow_reported_failure",
                                    retryable=False,
                                    phase="workflow_execution",
                                    message=result.reason or result.message,
                                    suggested_action=(
                                        "Inspect the workflow result reason and any output artifacts, then resume "
                                        "only the unfinished items or adjust the workflow before rerunning."
                                    ),
                                ),
                                output_files=result.output_files,
                                message=result.message,
                            ),
                        },
                    )
                await self._mark_task_terminal_from_result(active_task_id, result)
                return result
            except asyncio.CancelledError:
                self._log_workflow_event(
                    "workflow_task_cancelled",
                    global_id=global_id,
                    vault_name=vault_name,
                    workflow_name=workflow_name,
                    source=source_value,
                    task_id=active_task_id,
                    status="cancelled",
                    reason="cancelled",
                    step_name=step_name,
                    expect_failure=expect_failure,
                    include_load_errors=include_load_errors,
                )
                raise
            except Exception as exc:
                reason = f"{type(exc).__name__}: {exc}"
                classification = classify_exception(exc, phase="workflow_execution")
                failure_metadata = _build_workflow_failure_metadata(
                    global_id=global_id,
                    vault_name=vault_name,
                    workflow_name=workflow_name,
                    step_name=step_name,
                    source=source_value,
                    status="failed",
                    reason=reason,
                    classification=classification,
                    output_files=[],
                    message=str(exc),
                )
                await self._task_coordinator.update_metadata(
                    active_task_id,
                    {"workflow_failure": failure_metadata},
                )
                self._log_workflow_event(
                    "workflow_task_failed",
                    global_id=global_id,
                    vault_name=vault_name,
                    workflow_name=workflow_name,
                    source=source_value,
                    task_id=active_task_id,
                    status="failed",
                    reason=reason,
                    step_name=step_name,
                    expect_failure=expect_failure,
                    include_load_errors=include_load_errors,
                    failure_kind=classification.failure_kind,
                    retryable=classification.retryable,
                )
                raise
            finally:
                if global_permit_acquired and global_semaphore is not None:
                    global_semaphore.release()
                lane_lock.release()

    async def start_workflow(
        self,
        *,
        global_id: str,
        source: WorkflowSource,
        step_name: str | None = None,
        expect_failure: bool = False,
        include_load_errors: bool = False,
        background_tasks: set[asyncio.Task] | None = None,
    ) -> ExecutionTaskSnapshot:
        """Start one workflow in the background and return its execution task."""
        vault_name, _workflow_name = self._split_workflow_identity(global_id)
        task = await self._task_coordinator.create_queued_task(
            kind=ExecutionTaskKind.WORKFLOW,
            scope=workflow_vault_scope(vault_name),
            source=source,
            label=global_id,
            metadata={
                "workflow_id": global_id,
                "vault": vault_name,
                "step_name": step_name,
            },
        )

        async def _run() -> None:
            try:
                await self.execute_workflow(
                    global_id=global_id,
                    source=source,
                    step_name=step_name,
                    expect_failure=expect_failure,
                    include_load_errors=include_load_errors,
                    task_id=task.task_id,
                )
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                return

        def _spawn() -> None:
            background_task = asyncio.create_task(_run(), context=contextvars.Context())
            if background_tasks is not None:
                background_tasks.add(background_task)
                background_task.add_done_callback(background_tasks.discard)

        asyncio.get_running_loop().call_soon(_spawn, context=contextvars.Context())
        return task

    async def _get_lane_lock(self, vault_name: str) -> asyncio.Lock:
        async with self._lane_guard:
            lock = self._lane_locks.get(vault_name)
            if lock is None:
                lock = asyncio.Lock()
            self._lane_locks[vault_name] = lock
            return lock

    async def _get_global_semaphore(self) -> asyncio.Semaphore | None:
        limit = get_max_concurrent_workflows()
        if limit <= 0:
            return None
        async with self._global_limit_guard:
            if self._global_semaphore is None or self._global_limit != limit:
                self._global_limit = limit
                self._global_semaphore = asyncio.Semaphore(limit)
            return self._global_semaphore

    def _log_queue_event(
        self,
        event: str,
        *,
        global_id: str,
        vault_name: str,
        workflow_name: str,
        source: str,
        task_id: str,
        reason: str,
    ) -> None:
        self._logger.add_sink("validation").info(
            event,
            data={
                "event": event,
                "workflow_id": global_id,
                "workflow_name": workflow_name,
                "vault": vault_name,
                "source": source,
                "task_id": task_id,
                "reason": reason,
            },
        )

    def _log_workflow_event(
        self,
        event: str,
        *,
        global_id: str,
        vault_name: str,
        workflow_name: str,
        source: str,
        task_id: str,
        status: str | None = None,
        reason: str | None = None,
        step_name: str | None = None,
        expect_failure: bool | None = None,
        include_load_errors: bool | None = None,
        execution_time_seconds: float | None = None,
        output_files: list[str] | None = None,
        message: str | None = None,
        failure_kind: str | None = None,
        retryable: bool | None = None,
    ) -> None:
        self._logger.add_sink("validation").info(
            event,
            data={
                "event": event,
                "workflow_id": global_id,
                "workflow_name": workflow_name,
                "vault": vault_name,
                "source": source,
                "task_id": task_id,
                "status": status,
                "reason": reason,
                "step_name": step_name,
                "expect_failure": expect_failure,
                "include_load_errors": include_load_errors,
                "execution_time_seconds": execution_time_seconds,
                "output_files": list(output_files) if output_files is not None else None,
                "message": message,
                "failure_kind": failure_kind,
                "retryable": retryable,
            },
        )

    async def _mark_task_terminal_from_result(
        self,
        task_id: str,
        result: WorkflowExecutionResult,
    ) -> None:
        """Mirror a returned workflow status onto the execution task record."""
        status = str(result.status or "").strip().lower()
        reason = result.reason
        if status == ExecutionTaskStatus.SKIPPED.value:
            await self._task_coordinator.mark_skipped(task_id, reason=reason)
            return
        if status == ExecutionTaskStatus.FAILED.value:
            await self._task_coordinator.mark_failed(task_id, reason=reason)
            return
        if status == ExecutionTaskStatus.CANCELLED.value:
            await self._task_coordinator.mark_cancelled(task_id, reason=reason)
            return
        if status == ExecutionTaskStatus.TIMED_OUT.value:
            await self._task_coordinator.mark_timed_out(task_id, reason=reason)
            return
        await self._task_coordinator.mark_completed(task_id, reason=reason)

    @staticmethod
    def _split_workflow_identity(global_id: str) -> tuple[str, str]:
        if "/" not in global_id:
            raise ValueError(f"Invalid global_id format. Expected 'vault/name', got: {global_id}")
        vault_name, workflow_name = global_id.split("/", 1)
        return vault_name, workflow_name


def _build_workflow_failure_metadata(
    *,
    global_id: str,
    vault_name: str,
    workflow_name: str,
    step_name: str | None,
    source: str,
    status: str,
    reason: str | None,
    classification: FailureClassification,
    output_files: list[str],
    message: str | None,
) -> dict[str, Any]:
    """Build stable task metadata that helps agents recover from workflow failures."""
    metadata = classification.to_metadata()
    metadata.update(
        {
            "workflow_id": global_id,
            "workflow_name": workflow_name,
            "vault": vault_name,
            "source": source,
            "status": status,
            "phase": classification.phase,
            "reason": reason,
            "message": message or classification.message,
            "step_name": step_name,
            "output_files": list(output_files),
            "recovery_summary": {
                "completed_signal": "unknown",
                "remaining_signal": "unknown",
                "next_action": classification.suggested_action,
            },
        }
    )
    return metadata
