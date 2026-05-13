"""In-process scheduler job execution history."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock
from typing import Any

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED


_job_history: dict[str, dict[str, Any]] = {}
_lock = Lock()


def attach_scheduler_history_listener(scheduler: Any) -> None:
    """Attach the process-local scheduler job history listener."""
    scheduler.add_listener(record_scheduler_job_event, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)


def record_scheduler_job_event(event: Any) -> None:
    """Record the last terminal event for one scheduler job."""
    job_id = getattr(event, "job_id", None)
    if not job_id:
        return

    exception = getattr(event, "exception", None)
    row = {
        "last_run_time": datetime.now(UTC),
        "last_status": "error" if exception else "completed",
        "last_error": str(exception) if exception else None,
    }
    with _lock:
        _job_history[str(job_id)] = row


def get_scheduler_job_history(job_id: str) -> dict[str, Any] | None:
    """Return the latest process-local execution history for a scheduler job."""
    with _lock:
        row = _job_history.get(job_id)
        return dict(row) if row else None
