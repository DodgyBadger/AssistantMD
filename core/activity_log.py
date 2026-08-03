"""Retained System Activity segment inspection and query helpers."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from stat import S_ISREG
from typing import Any

DEFAULT_RETENTION_DAYS = 30
DEFAULT_MAX_TOTAL_BYTES = 100 * 1024 * 1024
DEFAULT_PAGE_SIZE = 200
MAX_PAGE_SIZE = 500


@dataclass(frozen=True)
class ActivityLogPage:
    """One newest-first page from retained System Activity."""

    entries: list[dict[str, Any]]
    next_cursor: str | None
    earliest_retained_timestamp: str | None
    total_matching: int
    total_size_bytes: int
    available_levels: list[str]
    available_tags: list[str]


@dataclass(frozen=True)
class ActivityPruneResult:
    """Outcome of one retained-segment cleanup pass."""

    removed_expired: int
    removed_for_size: int
    retained_bytes: int


def activity_log_paths(log_path: Path) -> list[Path]:
    """Return retained segments and the active log in chronological order."""

    candidates: list[tuple[int, str, Path]] = []
    for path in log_path.parent.glob(f"{log_path.name}.*"):
        if path.name.endswith(".lock"):
            continue
        if not path.name[len(log_path.name) + 1 : len(log_path.name) + 2].isdigit():
            continue
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        if not S_ISREG(stat.st_mode):
            continue
        candidates.append((stat.st_mtime_ns, path.name, path))
    segments = [path for _, _, path in sorted(candidates)]
    if log_path.exists():
        segments.append(log_path)
    return segments


def prune_activity_segments(
    log_path: Path,
    *,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    now: datetime | None = None,
) -> ActivityPruneResult:
    """Prune expired and oldest oversized retained segments."""

    current_time = now or datetime.now(UTC)
    cutoff = (current_time - timedelta(days=retention_days)).timestamp()
    retained_bytes = log_path.stat().st_size if log_path.exists() else 0
    removed_expired = 0
    removed_for_size = 0
    retained: list[tuple[Path, int]] = []

    segments = activity_log_paths(log_path)
    if segments and segments[-1] == log_path:
        segments = segments[:-1]

    for segment in segments:
        try:
            stat = segment.stat()
        except FileNotFoundError:
            continue
        if stat.st_mtime < cutoff:
            segment.unlink(missing_ok=True)
            removed_expired += 1
            continue
        retained.append((segment, stat.st_size))
        retained_bytes += stat.st_size

    for segment, size in retained:
        if retained_bytes <= max_total_bytes:
            break
        segment.unlink(missing_ok=True)
        retained_bytes -= size
        removed_for_size += 1

    return ActivityPruneResult(
        removed_expired=removed_expired,
        removed_for_size=removed_for_size,
        retained_bytes=retained_bytes,
    )


def query_activity_log(
    log_path: Path,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
    levels: Sequence[str] = (),
    tags: Sequence[str] = (),
    search: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> ActivityLogPage:
    """Query retained JSONL entries with stable newest-first cursor pagination."""

    page_size = max(1, min(int(limit), MAX_PAGE_SIZE))
    level_filter = {value.strip().lower() for value in levels if value.strip()}
    tag_filter = {value.strip() for value in tags if value.strip()}
    search_text = (search or "").strip().lower()
    start = _as_utc(start_time)
    end = _as_utc(end_time)
    cursor_key = _decode_cursor(cursor) if cursor else None

    records: list[tuple[tuple[str, str, int], dict[str, Any]]] = []
    available_levels: set[str] = set()
    available_tags: set[str] = set()
    earliest: datetime | None = None
    total_size = 0

    for segment_index, path in enumerate(activity_log_paths(log_path)):
        try:
            handle = path.open("r", encoding="utf-8", errors="replace")
            total_size += os.fstat(handle.fileno()).st_size
        except FileNotFoundError:
            continue
        with handle:
            for line_index, line in enumerate(handle):
                raw = line.rstrip("\r\n")
                if not raw:
                    continue
                entry = _parse_entry(raw)
                if entry is None:
                    continue
                timestamp = _parse_timestamp(entry.get("timestamp"))
                if timestamp is None:
                    continue
                earliest = (
                    timestamp if earliest is None or timestamp < earliest else earliest
                )
                level = str(entry.get("level") or "").lower()
                tag = str(entry.get("tag") or "")
                if level:
                    available_levels.add(level)
                if tag:
                    available_tags.add(tag)
                if start is not None and timestamp < start:
                    continue
                if end is not None and timestamp > end:
                    continue
                if level_filter and level not in level_filter:
                    continue
                if tag_filter and tag not in tag_filter:
                    continue
                if search_text and search_text not in raw.lower():
                    continue

                timestamp_key = timestamp.isoformat(timespec="milliseconds")
                digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
                key = (
                    timestamp_key,
                    digest,
                    segment_index * 1_000_000_000 + line_index,
                )
                entry["id"] = f"{timestamp_key}:{digest}:{line_index}"
                records.append((key, entry))

    records.sort(key=lambda item: item[0], reverse=True)
    if cursor_key is not None:
        records = [item for item in records if item[0] < cursor_key]

    total_matching = len(records)
    selected = records[:page_size]
    next_cursor = None
    if len(records) > page_size and selected:
        next_cursor = _encode_cursor(selected[-1][0])

    return ActivityLogPage(
        entries=[entry for _, entry in selected],
        next_cursor=next_cursor,
        earliest_retained_timestamp=(
            earliest.isoformat(timespec="milliseconds") if earliest else None
        ),
        total_matching=total_matching,
        total_size_bytes=total_size,
        available_levels=sorted(available_levels),
        available_tags=sorted(available_tags),
    )


def iter_activity_export(log_path: Path) -> Iterator[bytes]:
    """Yield all retained raw JSONL segments in chronological order."""

    for path in activity_log_paths(log_path):
        try:
            handle = path.open("rb")
        except FileNotFoundError:
            continue
        with handle:
            while chunk := handle.read(64 * 1024):
                yield chunk


def _parse_entry(raw: str) -> dict[str, Any] | None:
    try:
        record = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return record if isinstance(record, dict) else None


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_utc(parsed)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _encode_cursor(key: tuple[str, str, int]) -> str:
    payload = json.dumps(key, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> tuple[str, str, int]:
    try:
        padding = "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(value + padding))
        timestamp, digest, ordinal = decoded
        return str(timestamp), str(digest), int(ordinal)
    except (binascii.Error, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid activity log cursor") from exc
