"""
Runtime context for AssistantMD system.

Provides centralized access to core services and manages lifecycle
for scheduler, workflow loader, and related components.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core.workflow.loader import WorkflowLoader
from core.logger import UnifiedLogger
from core.scheduling.jobs import setup_scheduler_jobs
from core.ingestion.service import IngestionService
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
    """

    config: RuntimeConfig
    scheduler: AsyncIOScheduler
    workflow_loader: WorkflowLoader
    logger: UnifiedLogger
    ingestion: IngestionService
    boot_id: int
    started_at: datetime
    last_config_reload: Optional[datetime] = None

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

    async def reload_workflows(self, manual: bool = True):
        """
        Convenience method to reload workflow configurations.

        Delegates to existing setup_scheduler_jobs function while
        maintaining clean separation of concerns.

        Args:
            manual: Whether this is a manual reload (affects logging)
        """
        if manual:
            self.logger.info("Reloading workflows (manual=True)")
        return await setup_scheduler_jobs(self.scheduler, manual_reload=manual)

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


from . import state as runtime_state
