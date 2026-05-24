"""Shared session-summary status helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from core.chat.chat_store import StoredChatSession


STALE_SUMMARY_GRACE_MINUTES = 30


def session_summary_status(
    session: StoredChatSession,
    session_summary: object | None,
    *,
    message_count: int,
    stale_summary_min_new_messages: int,
) -> dict[str, object]:
    """Return current/pending/stale status metadata for one chat session summary."""
    if session_summary is None:
        return {
            "summary_status": "pending",
            "summary_updated_at": None,
            "summary_message_count": None,
            "new_message_count": message_count,
        }

    summary_updated_at = str(getattr(session_summary, "updated_at", "") or "")
    summary_message_count = summary_message_count_from_metadata(
        getattr(session_summary, "metadata", {}) or {}
    )
    new_message_count = (
        max(message_count - summary_message_count, 0)
        if summary_message_count is not None
        else None
    )
    session_last_activity = _parse_timestamp(session.last_activity_at)
    summary_updated = _parse_timestamp(summary_updated_at)
    if session_last_activity is None or summary_updated is None:
        stale = new_message_count is None or new_message_count >= stale_summary_min_new_messages
    else:
        grace_cutoff = summary_updated + timedelta(minutes=STALE_SUMMARY_GRACE_MINUTES)
        stale = (
            session_last_activity > grace_cutoff
            and (
                new_message_count is None
                or new_message_count >= stale_summary_min_new_messages
            )
        )

    return {
        "summary_status": "stale" if stale else "current",
        "summary_updated_at": summary_updated_at,
        "summary_message_count": summary_message_count,
        "new_message_count": new_message_count,
        "stale_summary_grace_minutes": STALE_SUMMARY_GRACE_MINUTES,
        "stale_summary_min_new_messages": stale_summary_min_new_messages,
    }


def summary_message_count_from_metadata(metadata: dict[str, Any]) -> int | None:
    """Return extraction-time message count from session-summary metadata."""
    raw = metadata.get("message_count")
    try:
        count = int(raw)
    except (TypeError, ValueError):
        return None
    return count if count >= 0 else None


def _parse_timestamp(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    if "T" not in normalized and " " in normalized:
        normalized = normalized.replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
