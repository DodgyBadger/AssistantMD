"""Shared session-summary status helpers."""

from __future__ import annotations

from typing import Any

from core.chat.chat_store import StoredChatSession


def session_summary_status(
    session: StoredChatSession,
    session_summary: object | None,
    *,
    message_count: int,
    history_revision: int | None = None,
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
            "history_revision": history_revision,
            "summary_history_revision": None,
            "history_revision_delta": None,
        }

    summary_updated_at = str(getattr(session_summary, "updated_at", "") or "")
    metadata = getattr(session_summary, "metadata", {}) or {}
    summary_message_count = summary_message_count_from_metadata(
        metadata
    )
    summary_history_revision = summary_history_revision_from_metadata(metadata)
    message_count_delta = (
        message_count - summary_message_count
        if summary_message_count is not None
        else None
    )
    history_revision_delta = (
        history_revision - summary_history_revision
        if history_revision is not None and summary_history_revision is not None
        else None
    )
    new_message_count = (
        max(message_count_delta, 0)
        if message_count_delta is not None
        else None
    )
    if history_revision_delta is not None:
        stale = history_revision_delta != 0
    else:
        stale = message_count_delta is not None and message_count_delta != 0

    return {
        "summary_status": "stale" if stale else "current",
        "summary_updated_at": summary_updated_at,
        "summary_message_count": summary_message_count,
        "message_count_delta": message_count_delta,
        "new_message_count": new_message_count,
        "history_revision": history_revision,
        "summary_history_revision": summary_history_revision,
        "history_revision_delta": history_revision_delta,
    }


def summary_message_count_from_metadata(metadata: dict[str, Any]) -> int | None:
    """Return extraction-time message count from session-summary metadata."""
    raw = metadata.get("message_count")
    return _non_negative_int(raw)


def summary_history_revision_from_metadata(metadata: dict[str, Any]) -> int | None:
    """Return extraction-time history revision from session-summary metadata."""
    raw = metadata.get("history_revision")
    return _non_negative_int(raw)


def _non_negative_int(raw: Any) -> int | None:
    try:
        count = int(raw)
    except (TypeError, ValueError):
        return None
    return count if count >= 0 else None
