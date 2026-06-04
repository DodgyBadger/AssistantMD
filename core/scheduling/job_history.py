"""In-process scheduler job execution history."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock
from typing import Any

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

from core.logger import UnifiedLogger


_job_history: dict[str, dict[str, Any]] = {}
_lock = Lock()
logger = UnifiedLogger(tag="scheduler-jobs")


def attach_scheduler_history_listener(scheduler: Any) -> None:
    """Attach the process-local scheduler job history listener."""
    scheduler.add_listener(
        lambda event: record_scheduler_job_event(event, scheduler=scheduler),
        EVENT_JOB_EXECUTED | EVENT_JOB_ERROR,
    )


def record_scheduler_job_event(event: Any, *, scheduler: Any | None = None) -> None:
    """Record the last terminal event for one scheduler job."""
    job_id = getattr(event, "job_id", None)
    if not job_id:
        return

    exception = getattr(event, "exception", None)
    status = "error" if exception else "completed"
    row = {
        "last_run_time": datetime.now(UTC),
        "last_status": status,
        "last_error": str(exception) if exception else None,
    }
    with _lock:
        _job_history[str(job_id)] = row

    _log_scheduler_terminal_event(event, scheduler=scheduler, status=status)


def get_scheduler_job_history(job_id: str) -> dict[str, Any] | None:
    """Return the latest process-local execution history for a scheduler job."""
    with _lock:
        row = _job_history.get(job_id)
        return dict(row) if row else None


def _log_scheduler_terminal_event(
    event: Any,
    *,
    scheduler: Any | None,
    status: str,
) -> None:
    """Emit activity for workflow scheduler terminal events and scheduler errors."""
    job_id = str(getattr(event, "job_id", ""))
    job_name = _get_job_name(scheduler, job_id)
    workflow_id = _workflow_id_from_job(job_id, job_name)
    exception = getattr(event, "exception", None)

    if workflow_id is None and exception is None:
        return

    result = getattr(event, "retval", None)
    result_fields = _workflow_result_fields(result)
    scheduled_run_time = getattr(event, "scheduled_run_time", None)
    if scheduled_run_time is not None:
        try:
            scheduled_run_time = scheduled_run_time.isoformat()
        except Exception:
            scheduled_run_time = str(scheduled_run_time)

    logger.add_sink("validation").info(
        "Scheduler job completed" if exception is None else "Scheduler job failed",
        data={
            "event": "scheduler_job_executed" if exception is None else "scheduler_job_error",
            "job_id": job_id,
            "job_name": job_name,
            "workflow_id": workflow_id,
            "workflow_name": _workflow_name(workflow_id),
            "scheduled_run_time": scheduled_run_time,
            "status": status,
            "error_type": type(exception).__name__ if exception else None,
            "error": str(exception) if exception else None,
            **result_fields,
        },
    )


def _get_job_name(scheduler: Any | None, job_id: str) -> str | None:
    """Return the scheduler job name if the job is still available."""
    if scheduler is None:
        return None
    try:
        job = scheduler.get_job(job_id)
    except Exception:
        return None
    return str(job.name) if job is not None and job.name is not None else None


def _workflow_id_from_job(job_id: str, job_name: str | None) -> str | None:
    """Return a workflow id for workflow jobs, if this looks like one."""
    prefix = "Workflow: "
    if job_name and job_name.startswith(prefix):
        return job_name[len(prefix) :]
    if "__" in job_id:
        return job_id.replace("__", "/")
    return None


def _workflow_name(workflow_id: str | None) -> str | None:
    """Return the workflow name portion of a vault-scoped workflow id."""
    if not workflow_id:
        return None
    return workflow_id.split("/", 1)[1] if "/" in workflow_id else workflow_id


def _workflow_result_fields(result: Any) -> dict[str, Any]:
    """Extract compact WorkflowExecutionResult fields from a scheduler retval."""
    if result is None:
        return {}

    return {
        "workflow_status": getattr(result, "status", None),
        "workflow_reason": getattr(result, "reason", None),
        "workflow_execution_time_seconds": getattr(result, "execution_time_seconds", None),
        "workflow_output_files": getattr(result, "output_files", None),
        "workflow_message": getattr(result, "message", None),
    }
