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
    ExecutionTaskSource,
    TaskCoordinator,
)


class IngestionWorker:
    def __init__(
        self,
        process_job_fn: Callable[[int], None],
        max_concurrent: int = 1,
        task_coordinator: TaskCoordinator | None = None,
    ):
        self.process_job_fn = process_job_fn
        self.max_concurrent = max_concurrent
        self.task_coordinator = task_coordinator
        self.logger = UnifiedLogger(tag="ingestion-worker")

    async def run_once(self):
        queued = [j for j in list_jobs(limit=100) if j.status == JobStatus.QUEUED.value]
        if not queued:
            return

        tasks = [
            asyncio.create_task(self._process_job(job.id))
            for job in queued[: self.max_concurrent]
        ]
        if tasks:
            await asyncio.gather(*tasks)

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
