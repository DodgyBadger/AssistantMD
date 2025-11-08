"""
Scheduler job management for dynamic assistant workflow scheduling.
Handles job setup, updates, and lifecycle management for APScheduler.
"""

from typing import Dict, Any

from core.logger import UnifiedLogger
from core.runtime.state import get_runtime_context

# Create scheduler job management logger
logger = UnifiedLogger(tag="scheduler-jobs")


def create_job_args(global_id: str, data_root: str = None):
    """Create picklable job arguments for workflow execution.

    Returns lightweight, serializable arguments with flexible config dictionary.
    This eliminates memory waste, enables SQLAlchemy job store serialization,
    and provides extensible configuration interface.

    Args:
        global_id: Assistant identifier (vault/name)
        data_root: Data root override (defaults to current runtime context data root)
    """
    if data_root is None:
        runtime = get_runtime_context()
        data_root = runtime.config.data_root

    return {
        'global_id': global_id,
        'config': {
            'data_root': str(data_root),
        }
    }






@logger.trace("setup_scheduler_jobs")
async def setup_scheduler_jobs(scheduler, manual_reload: bool = False) -> Dict[str, Any]:
    """
    Set up or update scheduler jobs based on vault-based configuration.

    Uses intelligent job synchronization to preserve timing state when possible:
    - If schedule/workflow unchanged: modify job args only (preserves timing)
    - If schedule/workflow changed: replace job completely (resets timing)
    - For new assistants: create new jobs

    Args:
        scheduler: APScheduler instance to update
        manual_reload: If True, manually triggered reload (e.g., from /rescan API)

    Returns:
        Dictionary with setup statistics:
        - vaults_discovered: Number of vaults found
        - assistants_loaded: Total assistants loaded
        - enabled_assistants: Number of enabled assistants
        - scheduler_jobs_synced: Number of jobs synchronized (includes no-change updates)

    Raises:
        Exception: If critical setup operations fail
    """
    # Load assistants from all vaults
    runtime = get_runtime_context()
    assistant_loader = runtime.assistant_loader

    assistants = await assistant_loader.load_assistants(force_reload=manual_reload)
    enabled_assistants = assistant_loader.get_enabled_assistants()

    # Calculate statistics
    vaults_discovered = len(set(assistant.vault for assistant in assistants))
    assistants_loaded = len(assistants)
    enabled_assistants_count = len(enabled_assistants)
    scheduler_jobs_synced = 0

    # Intelligent job synchronization for all enabled assistants
    if scheduler is not None:
        for assistant in enabled_assistants:
            # Skip assistants with no schedule - they are manual-only
            if assistant.trigger is None:
                continue

            # Ensure assistant directories exist
            await assistant_loader.ensure_assistant_directories(assistant)

            # Check if job already exists
            existing_job = scheduler.get_job(assistant.scheduler_job_id)

            if existing_job:
                # Intelligent synchronization - compare existing job vs desired config
                # Note: APScheduler triggers don't support == comparison, use string comparison
                schedule_changed = str(existing_job.trigger) != str(assistant.trigger)
                workflow_changed = existing_job.func != assistant.workflow_function

                if schedule_changed or workflow_changed:
                    # Full replacement - resets timing state
                    scheduler.remove_job(existing_job.id)

                    # Add new job with lightweight, picklable arguments
                    job_args = create_job_args(assistant.global_id)

                    scheduler.add_job(
                        func=assistant.workflow_function,
                        trigger=assistant.trigger,
                        args=[job_args],
                        id=assistant.scheduler_job_id,
                        name=f"Assistant: {assistant.global_id}"
                    )

                    logger.activity(
                        "Assistant job replaced (schedule/workflow changed)",
                        vault=assistant.global_id,
                        metadata={
                            "schedule": str(assistant.trigger),
                            "workflow": assistant.workflow_name,
                        },
                    )
                else:
                    # Safe update - preserve timing state, only update args
                    job_args = create_job_args(assistant.global_id)

                    scheduler.modify_job(
                        job_id=assistant.scheduler_job_id,
                        args=[job_args],
                        name=f"Assistant: {assistant.global_id}"
                    )

                    logger.activity(
                        "Assistant job updated (timing preserved)",
                        vault=assistant.global_id,
                        metadata={
                            "schedule": str(assistant.trigger),
                            "workflow": assistant.workflow_name,
                        },
                    )

                scheduler_jobs_synced += 1
            else:
                # New job
                job_args = create_job_args(assistant.global_id)

                scheduler.add_job(
                    func=assistant.workflow_function,
                    trigger=assistant.trigger,
                    args=[job_args],
                    id=assistant.scheduler_job_id,
                    name=f"Assistant: {assistant.global_id}"
                )

                logger.activity(
                    "Assistant job created",
                    vault=assistant.global_id,
                    metadata={
                        "schedule": str(assistant.trigger),
                        "workflow": assistant.workflow_name,
                    },
                )

                scheduler_jobs_synced += 1

        # Remove jobs for disabled assistants
        # Get all current job IDs in scheduler
        all_scheduler_job_ids = {job.id for job in scheduler.get_jobs()}
        # Get all job IDs that should exist (enabled assistants with schedules)
        enabled_job_ids = {
            assistant.scheduler_job_id
            for assistant in enabled_assistants
            if assistant.trigger is not None
        }
        # Find jobs that should be removed (in scheduler but not in enabled list)
        jobs_to_remove = all_scheduler_job_ids - enabled_job_ids

        for job_id in jobs_to_remove:
            scheduler.remove_job(job_id)
            logger.activity(
                "Removed job for disabled assistant",
                vault=job_id,
                metadata={"reason": "Assistant disabled or schedule removed"}
            )
    else:
        pass  # Scheduler not available - configurations loaded but jobs not updated

    # Prepare results
    results = {
        'vaults_discovered': vaults_discovered,
        'assistants_loaded': assistants_loaded,
        'enabled_assistants': enabled_assistants_count,
        'scheduler_jobs_synced': scheduler_jobs_synced
    }

    return results
