"""
APScheduler-driven worker to drain ingestion job queue.
"""

from __future__ import annotations

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

        for job in queued[: self.max_concurrent]:
            try:
                self.process_job_fn(job.id)
            except Exception as exc:
                self.logger.error(
                    "Failed to process ingestion job",
                    metadata={"job_id": job.id, "error": str(exc)},
                )
