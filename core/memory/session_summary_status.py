"""Shared session-summary status helpers."""

from __future__ import annotations

from typing import Any

from core.chat.chat_store import StoredChatSession


def session_summary_status(
    session: StoredChatSession,
    session_summary: object | None,
    *,
    message_count: int,
) -> dict[str, object]:
    """Return current/pending/stale status metadata for one chat session summary."""
    del session
    if session_summary is None:
        return {
            "summary_status": "pending",
            "summary_updated_at": None,
            "summary_message_count": None,
            "message_count_delta": None,
            "new_message_count": message_count,
        }

    summary_updated_at = str(getattr(session_summary, "updated_at", "") or "")
    summary_message_count = summary_message_count_from_metadata(
        getattr(session_summary, "metadata", {}) or {}
    )
    message_count_delta = (
        message_count - summary_message_count
        if summary_message_count is not None
        else None
    )
    new_message_count = (
        max(message_count_delta, 0)
        if message_count_delta is not None
        else None
    )
    stale = message_count_delta is not None and message_count_delta != 0

    return {
        "summary_status": "stale" if stale else "current",
        "summary_updated_at": summary_updated_at,
        "summary_message_count": summary_message_count,
        "message_count_delta": message_count_delta,
        "new_message_count": new_message_count,
    }


def summary_message_count_from_metadata(metadata: dict[str, Any]) -> int | None:
    """Return extraction-time message count from session-summary metadata."""
    raw = metadata.get("message_count")
    try:
        count = int(raw)
    except (TypeError, ValueError):
        return None
    return count if count >= 0 else None
