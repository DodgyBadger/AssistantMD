"""
Scheduler job management for dynamic workflow scheduling.
Handles job setup, updates, and lifecycle management for APScheduler.
"""

from typing import Dict, Any

from core.logger import UnifiedLogger
from core.runtime.state import get_runtime_context

# Create scheduler job management logger
logger = UnifiedLogger(tag="scheduler-jobs")

RESERVED_JOB_IDS = {
    # Non-workflow jobs scheduled elsewhere (e.g., ingestion worker) must be preserved
    "ingestion-worker",
}

def create_job_args(global_id: str, data_root: str = None):
    """Create picklable job arguments for workflow execution.

    Returns lightweight, serializable arguments with flexible config dictionary.
    This eliminates memory waste, enables SQLAlchemy job store serialization,
    and provides extensible configuration interface.

    Args:
        global_id: Workflow identifier (vault/name)
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
    Set up or update scheduler jobs based on vault workflow configuration.

    Uses intelligent job synchronization to preserve timing state when possible:
    - If schedule/workflow unchanged: modify job args only (preserves timing)
    - If schedule/workflow changed: replace job completely (resets timing)
    - For new workflows: create new jobs

    Args:
        scheduler: APScheduler instance to update
        manual_reload: If True, manually triggered reload (e.g., from /rescan API)

    Returns:
        Dictionary with setup statistics:
        - vaults_discovered: Number of vaults found
        - workflows_loaded: Total workflows loaded
        - enabled_workflows: Number of enabled workflows
        - scheduler_jobs_synced: Number of jobs synchronized (includes no-change updates)

    Raises:
        Exception: If critical setup operations fail
    """
    runtime = get_runtime_context()
    workflow_loader = runtime.workflow_loader

    workflows = await workflow_loader.load_workflows(force_reload=manual_reload)
    enabled_workflows = workflow_loader.get_enabled_workflows()

    vaults_discovered = len(set(workflow.vault for workflow in workflows))
    workflows_loaded = len(workflows)
    enabled_workflows_count = len(enabled_workflows)
    scheduler_jobs_synced = 0

    # Intelligent job synchronization for all enabled workflows
    if scheduler is not None:
        for workflow in enabled_workflows:
            if workflow.trigger is None:
                continue

            await workflow_loader.ensure_workflow_directories(workflow)

            existing_job = scheduler.get_job(workflow.scheduler_job_id)

            if existing_job:
                schedule_changed = str(existing_job.trigger) != str(workflow.trigger)
                workflow_changed = existing_job.func != workflow.workflow_function

                if schedule_changed or workflow_changed:
                    scheduler.remove_job(existing_job.id)

                    job_args = create_job_args(workflow.global_id)

                    scheduler.add_job(
                        func=workflow.workflow_function,
                        trigger=workflow.trigger,
                        args=[job_args],
                        id=workflow.scheduler_job_id,
                        name=f"Workflow: {workflow.global_id}"
                    )

                    logger.activity(
                        "Workflow job replaced (schedule/engine changed)",
                        vault=workflow.global_id,
                        metadata={
                            "schedule": str(workflow.trigger),
                            "workflow_engine": workflow.workflow_name,
                        },
                    )
                else:
                    job_args = create_job_args(workflow.global_id)

                    scheduler.modify_job(
                        job_id=workflow.scheduler_job_id,
                        args=[job_args],
                        name=f"Workflow: {workflow.global_id}"
                    )

                    logger.activity(
                        "Workflow job updated (timing preserved)",
                        vault=workflow.global_id,
                        metadata={
                            "schedule": str(workflow.trigger),
                            "workflow_engine": workflow.workflow_name,
                        },
                    )

                scheduler_jobs_synced += 1
            else:
                job_args = create_job_args(workflow.global_id)

                scheduler.add_job(
                    func=workflow.workflow_function,
                    trigger=workflow.trigger,
                    args=[job_args],
                    id=workflow.scheduler_job_id,
                    name=f"Workflow: {workflow.global_id}"
                )

                logger.activity(
                    "Workflow job created",
                    vault=workflow.global_id,
                    metadata={
                        "schedule": str(workflow.trigger),
                        "workflow_engine": workflow.workflow_name,
                    },
                )

                scheduler_jobs_synced += 1

        all_scheduler_job_ids = {
            job.id
            for job in scheduler.get_jobs()
            if job.id not in RESERVED_JOB_IDS
        }
        enabled_job_ids = {
            workflow.scheduler_job_id
            for workflow in enabled_workflows
            if workflow.trigger is not None
        }
        jobs_to_remove = all_scheduler_job_ids - enabled_job_ids

        for job_id in jobs_to_remove:
            scheduler.remove_job(job_id)
            logger.activity(
                "Removed job for disabled workflow",
                vault=job_id,
                metadata={"reason": "Workflow disabled or schedule removed"}
            )
    else:
        pass  # Scheduler not available - configurations loaded but jobs not updated

    # Prepare results
    results = {
        'vaults_discovered': vaults_discovered,
        'workflows_loaded': workflows_loaded,
        'enabled_workflows': enabled_workflows_count,
        'scheduler_jobs_synced': scheduler_jobs_synced
    }

    return results
