"""Administrative API services for retained application state."""

from datetime import datetime

from core.authoring.cache import purge_expired_cache_artifacts
from core.goals import GoalOpsStore

from ..models import CachePurgeResponse, GoalCleanupResponse
from .shared import logger


def purge_expired_cache() -> CachePurgeResponse:
    """Delete expired cache artifacts on demand."""
    now = datetime.now()
    purged_count = purge_expired_cache_artifacts(now=now)
    logger.info(
        "Manual cache purge completed",
        data={"purged_count": purged_count, "now": now.isoformat()},
    )
    return CachePurgeResponse(
        success=True,
        message=f"Purged {purged_count} expired cache artifact(s).",
        purged_count=purged_count,
    )


def cleanup_goals(
    vault_name: str,
    *,
    status: str,
    older_than_days: int | None,
) -> GoalCleanupResponse:
    """Delete old completed or cancelled goals for a vault."""
    status_key = (status or "completed").strip().lower()
    status_map = {
        "completed": ("completed",),
        "cancelled": ("cancelled",),
        "completed_or_cancelled": ("completed", "cancelled"),
    }
    statuses = status_map.get(status_key)
    if statuses is None:
        raise ValueError(
            "status must be completed, cancelled, or completed_or_cancelled"
        )

    deleted = GoalOpsStore().purge_goals(
        vault_name=vault_name,
        statuses=statuses,
        older_than_days=older_than_days,
    )
    logger.info(
        "Manual goal cleanup completed",
        data={
            "vault_name": vault_name,
            "status": status_key,
            "older_than_days": older_than_days,
            "deleted": deleted,
        },
    )
    if deleted == 0:
        message = "No goals matched."
    elif deleted == 1:
        message = "Deleted 1 goal."
    else:
        message = f"Deleted {deleted} goals."
    return GoalCleanupResponse(success=True, deleted=deleted, message=message)
