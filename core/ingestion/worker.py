"""
APScheduler-driven worker to drain ingestion job queue.
"""

from __future__ import annotations

import asyncio
from typing import Callable

from core.ingestion.jobs import get_job, list_jobs
from core.ingestion.models import JobStatus
from core.ingestion.task_execution import process_ingestion_job_in_task
from core.logger import UnifiedLogger
from core.runtime.execution_tasks import (
    ExecutionTaskKind,
    ExecutionTaskSource,
    TaskCoordinator,
    ingestion_task_label,
    ingestion_vault_scope,
)
from core.runtime.task_runner import ExecutionTaskHooks, ExecutionTaskRunner, ExecutionTaskSpec


class IngestionWorker:
    def __init__(
        self,
        process_job_fn: Callable[[int], None],
        max_concurrent: int = 1,
        task_coordinator: TaskCoordinator | None = None,
        task_runner: ExecutionTaskRunner | None = None,
    ):
        self.process_job_fn = process_job_fn
        self.max_concurrent = max_concurrent
        self.task_coordinator = task_coordinator
        self.task_runner = task_runner
        self.logger = UnifiedLogger(tag="ingestion-worker")

    async def run_once(self):
        queued = [j for j in list_jobs(limit=100) if j.status == JobStatus.QUEUED.value]
        if not queued:
            return

        selected_jobs = queued[: self.max_concurrent]
        if self.task_runner is not None and self.task_coordinator is not None:
            tracked_tasks = [
                await self._start_tracked_job(job.id)
                for job in selected_jobs
            ]
            await asyncio.gather(
                *(
                    self._wait_for_task_terminal(task.task_id)
                    for task in tracked_tasks
                )
            )
            return

        tasks = [asyncio.create_task(self._process_job(job.id)) for job in selected_jobs]
        await asyncio.gather(*tasks)

    async def _start_tracked_job(self, job_id: int):
        vault = self._job_vault(job_id)
        return await self.task_runner.start_background(
            ExecutionTaskSpec(
                kind=ExecutionTaskKind.INGESTION,
                scope=ingestion_vault_scope(vault),
                source=ExecutionTaskSource.SCHEDULER,
                label=ingestion_task_label(job_id),
                metadata={"job_id": job_id, "vault": vault},
            ),
            lambda _task: asyncio.to_thread(self.process_job_fn, job_id),
            hooks=ExecutionTaskHooks(
                on_failed=lambda _task_id, exc: self._log_job_failure(job_id, exc),
            ),
        )

    async def _process_job(self, job_id: int) -> None:
        try:
            if self.task_coordinator is None:
                await asyncio.to_thread(self.process_job_fn, job_id)
                return

            job = get_job(job_id)
            vault = job.vault if job is not None and job.vault else "unknown"
            await process_ingestion_job_in_task(
                task_coordinator=self.task_coordinator,
                process_job_fn=self.process_job_fn,
                job_id=job_id,
                vault=vault,
                source=ExecutionTaskSource.SCHEDULER,
            )
        except Exception as exc:
            self.logger.error(
                "Failed to process ingestion job",
                metadata={"job_id": job_id, "error": str(exc)},
            )

    def _job_vault(self, job_id: int) -> str:
        job = get_job(job_id)
        return job.vault if job is not None and job.vault else "unknown"

    async def _wait_for_task_terminal(self, task_id: str) -> None:
        if self.task_coordinator is None:
            return
        while True:
            task = await self.task_coordinator.get_task(task_id)
            if task is None or task.is_terminal:
                return
            await asyncio.sleep(0.05)

    async def _log_job_failure(self, job_id: int, exc: BaseException) -> None:
        self.logger.error(
            "Failed to process ingestion job",
            metadata={"job_id": job_id, "error": str(exc)},
        )
