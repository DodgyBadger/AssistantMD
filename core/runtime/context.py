"""
Runtime context for AssistantMD system.

Provides centralized access to core services and manages lifecycle
for scheduler, workflow loader, and related components.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core.authoring.template_discovery import WorkflowLoader
from core.logger import UnifiedLogger
from core.scheduling.jobs import setup_scheduler_jobs
from core.ingestion.service import IngestionService
from core.ingestion.worker import IngestionWorker
from core.runtime.background import RuntimeBackgroundSpawner
from core.runtime.buffers import BufferStore
from core.runtime.execution_tasks import TaskCoordinator
from core.runtime.workflow_governor import WorkflowGovernor
from core.vault_state import VaultStateService
from core.scheduling.system_jobs import sync_system_scheduler_jobs
from . import state as runtime_state
from .config import RuntimeConfig


@dataclass
class RuntimeContext:
    """
    Central runtime context for AssistantMD services.

    Manages lifecycle and provides access to core services including
    scheduler, workflow loader, and configuration. Supports both
    async and sync teardown for different use cases.

    Attributes:
        config: Runtime configuration
        scheduler: APScheduler instance for job management
        workflow_loader: Workflow configuration loader
        logger: Unified logger for runtime operations
        last_config_reload: Timestamp of most recent configuration reload (if any)
        ingestion: IngestionService
        ingestion_worker: IngestionWorker
        task_coordinator: Process-local execution task tracker
        workflow_governor: Workflow execution policy layer
    """

    config: RuntimeConfig
    scheduler: AsyncIOScheduler
    workflow_loader: WorkflowLoader
    logger: UnifiedLogger
    ingestion: IngestionService
    ingestion_worker: IngestionWorker
    ingestion_interval: int
    task_coordinator: TaskCoordinator
    workflow_governor: WorkflowGovernor
    background_spawner: RuntimeBackgroundSpawner
    boot_id: int
    started_at: datetime
    last_config_reload: Optional[datetime] = None
    session_buffers: dict[str, BufferStore] = field(default_factory=dict)
    background_tasks: set[asyncio.Task] = field(default_factory=set)

    async def start(self):
        """
        Start runtime services if needed.

        Currently a no-op since services are started during bootstrap,
        but provides extension point for future startup logic.
        """
        pass

    async def shutdown(self):
        """Gracefully shutdown all runtime services and clear global context."""
        self.logger.info("Shutting down runtime context")

        await self.task_coordinator.shutdown(reason="runtime_shutdown")

        if self.background_tasks:
            for task in list(self.background_tasks):
                task.cancel()
            await asyncio.gather(*self.background_tasks, return_exceptions=True)
            self.background_tasks.clear()

        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown(wait=True)

        # Clear global runtime context to allow clean restart
        runtime_state.clear_runtime_context()

    def sync_shutdown(self):
        """
        Synchronous wrapper for shutdown.

        Handles cases where async shutdown is needed from sync code,
        such as validation controllers or cleanup handlers.
        """
        try:
            # Check if we're already in an event loop
            loop = asyncio.get_running_loop()
            # If we are, schedule the shutdown as a task
            task = loop.create_task(self.shutdown())
            # Note: This doesn't wait for completion to avoid blocking
            # the event loop. Caller should await the task if needed.
            return task
        except RuntimeError:
            # No event loop running, safe to use asyncio.run
            asyncio.run(self.shutdown())

    async def reload_workflows(
        self,
        manual: bool = True,
        *,
        refresh_vault_state: bool = True,
    ):
        """
        Convenience method to reload workflow configurations.

        Delegates to existing setup_scheduler_jobs function while
        maintaining clean separation of concerns.

        Args:
            manual: Whether this is a manual reload (affects logging)
        """
        if manual:
            self.logger.info("Reloading workflows (manual=True)")
        results = await setup_scheduler_jobs(self.scheduler, manual_reload=manual)
        results.update(self.sync_system_scheduler_jobs())
        if not refresh_vault_state:
            return results
        try:
            vault_state_results = VaultStateService().refresh_all_vaults(self.config.data_root)
        except Exception as exc:  # noqa: BLE001
            self.logger.add_sink("validation").warning(
                "vault_state_refresh_all_failed",
                data={
                    "event": "vault_state_refresh_all_failed",
                    "manual": manual,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            vault_state_results = {
                "vault_state_enabled": True,
                "vault_state_refreshed": 0,
                "vault_state_failed": 1,
            }
        results.update(vault_state_results)
        return results

    def start_background_vault_state_refresh(self, *, reason: str) -> None:
        """Start a non-blocking refresh of all vault-state manifests."""
        self.background_spawner.spawn(
            lambda: self._refresh_vault_state_in_background(reason=reason)
        )

    async def _refresh_vault_state_in_background(self, *, reason: str) -> None:
        self.logger.add_sink("validation").info(
            "Starting background vault-state refresh",
            data={
                "event": "vault_state_background_refresh_started",
                "reason": reason,
            },
        )
        try:
            result = await asyncio.to_thread(
                VaultStateService().refresh_all_vaults,
                self.config.data_root,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self.logger.add_sink("validation").warning(
                "vault_state_background_refresh_failed",
                data={
                    "event": "vault_state_background_refresh_failed",
                    "reason": reason,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            return
        self.logger.add_sink("validation").info(
            "Background vault-state refresh completed",
            data={
                "event": "vault_state_background_refresh_completed",
                "reason": reason,
                "vault_state_enabled": result.get("vault_state_enabled"),
                "vault_state_refreshed": result.get("vault_state_refreshed"),
                "vault_state_failed": result.get("vault_state_failed"),
                "vault_state_latest_sequence": result.get("vault_state_latest_sequence"),
            },
        )

    def sync_system_scheduler_jobs(self) -> dict[str, int]:
        """Synchronize built-in scheduler jobs with current settings."""
        return sync_system_scheduler_jobs(
            scheduler=self.scheduler,
            data_root=self.config.data_root,
            ingestion_worker=self.ingestion_worker,
            ingestion_interval=self.ingestion_interval,
        )

    def get_runtime_summary(self) -> dict:
        """
        Get runtime context summary for diagnostics.

        Returns basic information about the runtime state without
        exposing internal objects.
        """
        scheduler_info = "not_available"
        if self.scheduler:
            if self.scheduler.running:
                scheduler_info = f"running ({len(self.scheduler.get_jobs())} jobs)"
            else:
                scheduler_info = "stopped"

        return {
            "data_root": str(self.config.data_root),
            "system_root": str(self.config.system_root),
            "scheduler": scheduler_info,
            "features": self.config.features,
            "log_level": self.config.log_level
        }
