"""
Runtime bootstrap for AssistantMD system.

Provides single entry point for initializing all runtime services
with proper configuration, error handling, and lifecycle management.
"""

from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core.workflow.loader import WorkflowLoader
from core.logger import UnifiedLogger
from core.scheduling.database import create_job_store
from core.settings import validate_settings
from core.settings.store import get_general_settings
from core.ingestion.service import IngestionService
from core.ingestion.worker import IngestionWorker
# Note: Job setup now handled via runtime_context.reload_workflows()
from .config import RuntimeConfig, RuntimeConfigError
from .context import RuntimeContext
from .state import set_runtime_context, clear_runtime_context
from .paths import set_bootstrap_roots
from . import state as runtime_state


async def bootstrap_runtime(config: RuntimeConfig) -> RuntimeContext:
    """
    Bootstrap AssistantMD runtime with centralized service initialization.

    Creates and configures all core services using the provided configuration,
    establishes scheduler with job persistence, and returns a unified context
    for accessing services throughout the application lifecycle.

    Args:
        config: Runtime configuration with paths and settings

    Returns:
        RuntimeContext with initialized services

    Raises:
        RuntimeBootstrapError: If bootstrap process fails
        RuntimeConfigError: If configuration is invalid
        RuntimeStartupError: If service initialization fails
    """
    logger = UnifiedLogger(tag="runtime-bootstrap")
    logger.info("Starting runtime bootstrap", metadata={"data_root": str(config.data_root)})

    try:
        # Make bootstrap roots available for helpers that run before context is set
        set_bootstrap_roots(config.data_root, config.system_root)

        # Validate configuration before continuing bootstrap
        config_status = validate_settings()
        if not config_status.is_healthy:
            error_messages = [f"{issue.name}: {issue.message}" for issue in config_status.errors]
            logger.error(
                "Critical configuration validation failed",
                metadata={"errors": error_messages},
            )
            raise RuntimeConfigError("; ".join(error_messages))

        for warning in config_status.warnings:
            logger.warning(
                warning.message,
                metadata={"issue": warning.name, "severity": warning.severity},
            )

        # Ensure env defaults reflect the configured roots before services that read env/context
        import os

        os.environ["CONTAINER_DATA_ROOT"] = str(config.data_root)
        os.environ["CONTAINER_SYSTEM_ROOT"] = str(config.system_root)
        os.environ.setdefault("SECRETS_PATH", str(Path(config.system_root) / "secrets.yaml"))

        # Initialize workflow loader with configured data root
        workflow_loader = WorkflowLoader(
            _data_root=str(config.data_root),
            _allow_direct_instantiation=True
        )

        # Initialize ingestion service
        ingestion_service = IngestionService()
        # Determine ingestion worker interval and batch size from settings (with safe fallbacks)
        ingestion_interval = 120
        ingestion_max_concurrent = (
            config.features.get("ingestion_max_concurrent", 1)
            if isinstance(config.features, dict)
            else 1
        )
        try:
            general_settings = get_general_settings()
            ingestion_interval = int(
                general_settings.get("ingestion_worker_interval_seconds").value
            )
            try:
                ingestion_max_concurrent = int(
                    general_settings.get("ingestion_worker_batch_size").value
                )
            except Exception:
                pass
        except Exception:
            pass

        ingestion_worker = IngestionWorker(
            process_job_fn=ingestion_service.process_job,
            max_concurrent=ingestion_max_concurrent,
        )

        # Create persistent job store for scheduler
        job_store = create_job_store(system_root=str(config.system_root))

        # Initialize scheduler with job store and worker configuration
        jobstores = {"default": job_store}
        scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            max_workers=config.max_scheduler_workers
        )

        # Start scheduler in paused mode to allow job synchronization
        scheduler.start(paused=True)
        logger.info("Scheduler started in paused mode for job synchronization")

        # Create runtime context with all initialized services
        boot_id = runtime_state.next_boot_id()
        started_at = datetime.utcnow()
        runtime_context = RuntimeContext(
            config=config,
            scheduler=scheduler,
            workflow_loader=workflow_loader,
            logger=logger,
            ingestion=ingestion_service,
            boot_id=boot_id,
            started_at=started_at,
        )

        # Register context globally before job synchronization
        set_runtime_context(runtime_context)

        try:
            # Load workflow configurations and synchronize jobs using runtime context
            await runtime_context.reload_workflows(manual=False)
            logger.info("Workflow configurations loaded and jobs synchronized")

            # Schedule ingestion worker
            scheduler.add_job(
                ingestion_worker.run_once,
                "interval",
                seconds=ingestion_interval,
                id="ingestion-worker",
                name="Ingestion worker",
                max_instances=1,
                replace_existing=True,
            )

            # Resume scheduler after successful synchronization
            scheduler.resume()
            logger.info("Scheduler resumed and ready for execution")

        except Exception:
            # If job synchronization fails, clean up and rethrow
            scheduler.shutdown(wait=False)
            clear_runtime_context()
            raise

        logger.info(
            "Runtime bootstrap completed successfully",
            data={
                "data_root": str(config.data_root),
                "system_root": str(config.system_root),
                "scheduler_workers": config.max_scheduler_workers,
                "features": config.features,
            },
        )

        return runtime_context

    except RuntimeConfigError:
        # Re-raise configuration errors without wrapping
        raise

    except Exception as e:
        # Wrap any other errors in startup error for clear error handling
        logger.error(f"Runtime bootstrap failed: {e}")

        # Attempt cleanup of any partially initialized services
        try:
            if 'scheduler' in locals() and scheduler and scheduler.running:
                scheduler.shutdown(wait=False)
        except Exception as cleanup_error:
            logger.error(f"Error during bootstrap cleanup: {cleanup_error}")

        raise RuntimeStartupError(f"Failed to bootstrap runtime: {e}") from e


class RuntimeBootstrapError(Exception):
    """Base exception for runtime bootstrap failures."""
    pass


class RuntimeStartupError(RuntimeBootstrapError):
    """Raised when service initialization fails during bootstrap."""
    pass
