"""
Runtime bootstrap for AssistantMD system.

Provides single entry point for initializing all runtime services
with proper configuration, error handling, and lifecycle management.
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core.assistant.loader import AssistantLoader
from core.logger import UnifiedLogger
from core.scheduling.database import create_job_store
from core.settings import validate_settings
# Note: Job setup now handled via runtime_context.reload_assistants()
from .config import RuntimeConfig, RuntimeConfigError
from .context import RuntimeContext
from .state import set_runtime_context, clear_runtime_context


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

        # Initialize assistant loader with configured data root
        assistant_loader = AssistantLoader(
            _data_root=str(config.data_root),
            _allow_direct_instantiation=True
        )

        # Create persistent job store for scheduler
        job_store = create_job_store(system_data_root=str(config.system_data_root))

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
        runtime_context = RuntimeContext(
            config=config,
            scheduler=scheduler,
            assistant_loader=assistant_loader,
            logger=logger
        )

        # Register context globally before job synchronization
        set_runtime_context(runtime_context)

        try:
            # Load assistant configurations and synchronize jobs using runtime context
            await runtime_context.reload_assistants(manual=False)
            logger.info("Assistant configurations loaded and jobs synchronized")

            # Resume scheduler after successful synchronization
            scheduler.resume()
            logger.info("Scheduler resumed and ready for execution")

        except Exception:
            # If job synchronization fails, clean up and rethrow
            scheduler.shutdown(wait=False)
            clear_runtime_context()
            raise

        logger.activity(
            "Runtime bootstrap completed successfully",
            vault="system",
            metadata={
                "data_root": str(config.data_root),
                "system_data_root": str(config.system_data_root),
                "scheduler_workers": config.max_scheduler_workers,
                "features": config.features
            }
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
