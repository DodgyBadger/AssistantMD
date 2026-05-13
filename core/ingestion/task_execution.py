"""Execution-task wrappers for ingestion jobs."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from core.runtime.execution_tasks import (
    ExecutionTaskKind,
    ExecutionTaskSource,
    TaskCoordinator,
    ingestion_task_label,
    ingestion_vault_scope,
)


async def process_ingestion_job_in_task(
    *,
    task_coordinator: TaskCoordinator,
    process_job_fn: Callable[[int], None],
    job_id: int,
    vault: str,
    source: ExecutionTaskSource,
) -> None:
    """Run one ingestion job in a task context that vault mutations can audit."""
    async with task_coordinator.track_current_task(
        kind=ExecutionTaskKind.INGESTION,
        scope=ingestion_vault_scope(vault),
        source=source,
        label=ingestion_task_label(job_id),
        metadata={"job_id": job_id, "vault": vault},
    ):
        await asyncio.to_thread(process_job_fn, job_id)
