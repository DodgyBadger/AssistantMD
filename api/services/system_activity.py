"""API services for retained System Activity inspection and export."""

from collections.abc import Iterator
from datetime import datetime

from core.activity_log import iter_activity_export, query_activity_log
from core.runtime.paths import get_system_root

from ..exceptions import APIException, SystemConfigurationError
from ..models import SystemActivityEntryInfo, SystemLogResponse


async def get_system_activity_log(
    *,
    limit: int = 200,
    cursor: str | None = None,
    levels: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
    search: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> SystemLogResponse:
    """Return one filtered newest-first page from retained System Activity."""
    log_path = get_system_root() / "activity.log"
    try:
        page = query_activity_log(
            log_path,
            limit=limit,
            cursor=cursor,
            levels=levels,
            tags=tags,
            search=search,
            start_time=start_time,
            end_time=end_time,
        )
    except ValueError as exc:
        raise APIException(
            status_code=400,
            error_type="InvalidActivityCursor",
            message=str(exc),
        ) from exc
    except OSError as exc:
        raise SystemConfigurationError(f"Failed to query activity log: {exc}") from exc

    earliest = (
        datetime.fromisoformat(page.earliest_retained_timestamp)
        if page.earliest_retained_timestamp
        else None
    )
    return SystemLogResponse(
        entries=[
            SystemActivityEntryInfo.model_validate(entry) for entry in page.entries
        ],
        next_cursor=page.next_cursor,
        earliest_retained_timestamp=earliest,
        total_matching=page.total_matching,
        retained_size_bytes=page.total_size_bytes,
        available_levels=page.available_levels,
        available_tags=page.available_tags,
    )


def export_system_activity_log() -> Iterator[bytes]:
    """Yield retained raw System Activity JSONL in chronological order."""
    return iter_activity_export(get_system_root() / "activity.log")
