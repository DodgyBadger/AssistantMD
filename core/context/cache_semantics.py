from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Any


_DURATION_PATTERN = re.compile(r"^(?P<amount>\d+)\s*(?P<unit>[smhd])$")
_UNIT_SECONDS = {
    "s": 1,
    "m": 60,
    "h": 60 * 60,
    "d": 60 * 60 * 24,
}
_NAMED_MODES = {"daily", "weekly", "session"}


def parse_cache_mode_value(value: str) -> dict[str, Any]:
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("Cache mode cannot be empty")
    if normalized in _NAMED_MODES:
        return {"mode": normalized, "ttl_seconds": None}

    match = _DURATION_PATTERN.match(normalized)
    if not match:
        raise ValueError(
            "Expected cache ttl like 10m/24h/1d or one of: daily, weekly, session"
        )

    amount = int(match.group("amount"))
    if amount <= 0:
        raise ValueError("Cache duration must be greater than 0")

    ttl_seconds = amount * _UNIT_SECONDS[match.group("unit")]
    return {"mode": "duration", "ttl_seconds": ttl_seconds}


def parse_db_timestamp(raw_value: str | None) -> datetime | None:
    if not raw_value:
        return None
    try:
        return datetime.fromisoformat(raw_value)
    except ValueError:
        try:
            return datetime.strptime(raw_value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None


def start_of_week(value: datetime, week_start_day: int) -> datetime:
    delta_days = (value.weekday() - week_start_day) % 7
    return (value - timedelta(days=delta_days)).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )


def cache_entry_is_valid(
    *,
    created_at: str | None,
    cache_mode: str,
    ttl_seconds: int | None,
    now: datetime,
    week_start_day: int,
) -> bool:
    created_dt = parse_db_timestamp(created_at)
    if created_dt is None:
        return False
    if created_dt.tzinfo is None and now.tzinfo is not None:
        created_dt = created_dt.replace(tzinfo=timezone.utc)
    elif created_dt.tzinfo is not None and now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if cache_mode == "duration":
        if ttl_seconds is None:
            return False
        return now - created_dt < timedelta(seconds=ttl_seconds)
    if cache_mode == "daily":
        return created_dt.date() == now.date()
    if cache_mode == "weekly":
        return start_of_week(created_dt, week_start_day) == start_of_week(now, week_start_day)
    if cache_mode == "session":
        return True
    return False


def compute_cache_expiration(
    *,
    created_at: datetime,
    cache_mode: str,
    ttl_seconds: int | None,
    week_start_day: int,
) -> datetime | None:
    if cache_mode == "session":
        return None
    if cache_mode == "duration":
        if ttl_seconds is None:
            raise ValueError("Duration cache entries require ttl_seconds")
        return created_at + timedelta(seconds=ttl_seconds)
    if cache_mode == "daily":
        return (created_at + timedelta(days=1)).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
    if cache_mode == "weekly":
        return start_of_week(created_at, week_start_day) + timedelta(days=7)
    raise ValueError(f"Unsupported cache mode '{cache_mode}'")
