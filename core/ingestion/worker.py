"""
APScheduler-driven worker to drain ingestion job queue.
"""

from __future__ import annotations

import asyncio
from typing import Callable

from core.ingestion.jobs import list_jobs
from core.ingestion.models import JobStatus
from core.logger import UnifiedLogger


class IngestionWorker:
    def __init__(self, process_job_fn: Callable[[int], None], max_concurrent: int = 1):
        self.process_job_fn = process_job_fn
        self.max_concurrent = max_concurrent
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
            # Run the CPU/disk-bound pipeline in a worker thread so we do not block the event loop
            await asyncio.to_thread(self.process_job_fn, job_id)
        except Exception as exc:
            self.logger.error(
                "Failed to process ingestion job",
                metadata={"job_id": job_id, "error": str(exc)},
            )
