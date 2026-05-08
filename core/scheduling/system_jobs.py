"""Built-in APScheduler jobs owned by the AssistantMD runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.ingestion.worker import IngestionWorker
from core.logger import UnifiedLogger
from core.settings import get_vault_scan_interval_seconds, get_vault_state_enabled
from core.vault_state import VaultStateService


INGESTION_WORKER_JOB_ID = "ingestion-worker"
VAULT_STATE_REFRESH_JOB_ID = "vault-state-refresh"
SYSTEM_JOB_IDS = frozenset({INGESTION_WORKER_JOB_ID, VAULT_STATE_REFRESH_JOB_ID})

logger = UnifiedLogger(tag="system-scheduler-jobs")


def run_scheduled_vault_state_refresh(data_root: str) -> dict[str, Any]:
    """Refresh all vault-state manifests for the scheduler job store."""
    result = VaultStateService().refresh_all_vaults(Path(data_root))
    logger.info(
        "Vault state scheduled refresh completed",
        data={
            "event": "vault_state_scheduled_refresh_completed",
            "data_root": data_root,
            "vault_state_enabled": result.get("vault_state_enabled"),
            "vault_state_refreshed": result.get("vault_state_refreshed"),
            "vault_state_failed": result.get("vault_state_failed"),
            "vault_state_latest_sequence": result.get("vault_state_latest_sequence"),
        },
    )
    return result


def sync_system_scheduler_jobs(
    *,
    scheduler: Any,
    data_root: str | Path,
    ingestion_worker: IngestionWorker | None,
    ingestion_interval: int,
) -> dict[str, int]:
    """Create, update, or remove built-in scheduler jobs."""
    if scheduler is None:
        return {"system_jobs_synced": 0, "system_jobs_removed": 0}

    synced = 0
    removed = 0

    if ingestion_worker is not None:
        scheduler.add_job(
            ingestion_worker.run_once,
            "interval",
            seconds=max(int(ingestion_interval), 1),
            id=INGESTION_WORKER_JOB_ID,
            name="Ingestion worker",
            max_instances=1,
            replace_existing=True,
        )
        synced += 1

    vault_scan_interval = get_vault_scan_interval_seconds()
    if get_vault_state_enabled() and vault_scan_interval > 0:
        scheduler.add_job(
            run_scheduled_vault_state_refresh,
            "interval",
            seconds=vault_scan_interval,
            args=[str(data_root)],
            id=VAULT_STATE_REFRESH_JOB_ID,
            name="Vault state refresh",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        synced += 1
    else:
        existing = scheduler.get_job(VAULT_STATE_REFRESH_JOB_ID)
        if existing is not None:
            scheduler.remove_job(VAULT_STATE_REFRESH_JOB_ID)
            removed += 1

    if synced or removed:
        logger.info(
            "System scheduler jobs synced",
            data={
                "event": "system_scheduler_jobs_synced",
                "system_jobs_synced": synced,
                "system_jobs_removed": removed,
                "vault_scan_interval_seconds": vault_scan_interval,
            },
        )

    return {"system_jobs_synced": synced, "system_jobs_removed": removed}
