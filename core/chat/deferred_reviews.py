"""Durable storage for chat inline review requests backed by deferred tools."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import TypeAdapter
from pydantic_ai import DeferredToolRequests, DeferredToolResults
from pydantic_ai.messages import ModelMessage, ToolCallPart

from core.database import connect_sqlite_from_system_db
from core.logger import UnifiedLogger

from .schema import DB_NAME, ensure_chat_sessions_schema


logger = UnifiedLogger(tag="chat-deferred-reviews")

_DEFERRED_TOOL_REQUESTS_ADAPTER = TypeAdapter(DeferredToolRequests)
_DEFERRED_TOOL_RESULTS_ADAPTER = TypeAdapter(DeferredToolResults)
_MODEL_MESSAGE_LIST_ADAPTER = TypeAdapter(list[ModelMessage])


class DeferredReviewError(ValueError):
    """Raised when a deferred review cannot be used."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class StoredDeferredReview:
    """One persisted inline review request created from deferred tool calls."""

    artifact_ref: str
    session_id: str
    vault_name: str
    originating_task_id: str
    status: str
    requests: DeferredToolRequests
    resume_messages: list[ModelMessage]
    resume_config: dict[str, Any]
    created_at: str
    submitted_at: str | None = None
    resumed_task_id: str | None = None
    result_json: str | None = None
    error_json: str | None = None

    @property
    def review_count(self) -> int:
        """Return the number of deferred review calls in this request."""
        return len(self.requests.approvals) + len(self.requests.calls)


def create_deferred_review(
    *,
    vault_name: str,
    session_id: str,
    originating_task_id: str,
    requests: DeferredToolRequests,
    resume_messages: list[ModelMessage],
    resume_config: dict[str, Any],
) -> StoredDeferredReview:
    """Persist one pending deferred review request and return it."""
    artifact_ref = f"deferred-review-{uuid.uuid4().hex}"
    requests_json = _DEFERRED_TOOL_REQUESTS_ADAPTER.dump_json(requests).decode("utf-8")
    resume_messages_json = _MODEL_MESSAGE_LIST_ADAPTER.dump_json(resume_messages).decode("utf-8")
    resume_config_json = json.dumps(resume_config, ensure_ascii=False, sort_keys=True)

    ensure_chat_sessions_schema()
    conn = connect_sqlite_from_system_db(DB_NAME)
    conn.row_factory = _dict_row_factory
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            INSERT INTO chat_sessions (session_id, vault_name)
            VALUES (?, ?)
            ON CONFLICT(session_id, vault_name)
            DO UPDATE SET last_activity_at = CURRENT_TIMESTAMP
            """,
            (session_id, vault_name),
        )
        conn.execute(
            """
            INSERT INTO chat_deferred_reviews (
                artifact_ref,
                session_id,
                vault_name,
                originating_task_id,
                status,
                requests_json,
                resume_messages_json,
                resume_config_json
            ) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)
            """,
            (
                artifact_ref,
                session_id,
                vault_name,
                originating_task_id,
                requests_json,
                resume_messages_json,
                resume_config_json,
            ),
        )
        row = conn.execute(
            """
            SELECT artifact_ref, session_id, vault_name, originating_task_id,
                   status, requests_json, resume_messages_json,
                   resume_config_json, result_json, created_at, submitted_at,
                   resumed_task_id, error_json
            FROM chat_deferred_reviews
            WHERE artifact_ref = ?
            """,
            (artifact_ref,),
        ).fetchone()
        conn.commit()
    finally:
        conn.close()

    review = _review_from_row(row)
    logger.info(
        "chat_deferred_review_created",
        data={
            "event": "chat_deferred_review_created",
            "artifact_ref": review.artifact_ref,
            "vault_name": vault_name,
            "session_id": session_id,
            "originating_task_id": originating_task_id,
            "review_count": review.review_count,
            "tool_names": _tool_names(review.requests),
        },
    )
    return review


def get_deferred_review(
    *,
    vault_name: str,
    session_id: str,
    artifact_ref: str,
) -> StoredDeferredReview | None:
    """Return one deferred review request, if it belongs to the chat session."""
    ensure_chat_sessions_schema()
    conn = connect_sqlite_from_system_db(DB_NAME)
    conn.row_factory = _dict_row_factory
    try:
        row = conn.execute(
            """
            SELECT artifact_ref, session_id, vault_name, originating_task_id,
                   status, requests_json, resume_messages_json,
                   resume_config_json, result_json, created_at, submitted_at,
                   resumed_task_id, error_json
            FROM chat_deferred_reviews
            WHERE artifact_ref = ? AND session_id = ? AND vault_name = ?
            """,
            (artifact_ref, session_id, vault_name),
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else _review_from_row(row)


def mark_deferred_review_submitted(
    *,
    vault_name: str,
    session_id: str,
    artifact_ref: str,
    results: DeferredToolResults,
    resumed_task_id: str,
) -> StoredDeferredReview:
    """Mark a pending deferred review submitted and linked to a resume task."""
    result_json = _DEFERRED_TOOL_RESULTS_ADAPTER.dump_json(results).decode("utf-8")
    ensure_chat_sessions_schema()
    conn = connect_sqlite_from_system_db(DB_NAME)
    conn.row_factory = _dict_row_factory
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        existing = conn.execute(
            """
            SELECT artifact_ref, session_id, vault_name, originating_task_id,
                   status, requests_json, resume_messages_json,
                   resume_config_json, result_json, created_at, submitted_at,
                   resumed_task_id, error_json
            FROM chat_deferred_reviews
            WHERE artifact_ref = ? AND session_id = ? AND vault_name = ?
            """,
            (artifact_ref, session_id, vault_name),
        ).fetchone()
        if existing is None:
            raise DeferredReviewError(
                "DeferredReviewNotFound",
                "Deferred review request was not found for this chat session.",
                details={
                    "artifact_ref": artifact_ref,
                    "session_id": session_id,
                    "vault_name": vault_name,
                },
            )
        if str(existing["status"]) != "pending":
            raise DeferredReviewError(
                "DeferredReviewAlreadySubmitted",
                "Deferred review request has already been submitted.",
                details={
                    "artifact_ref": artifact_ref,
                    "status": str(existing["status"]),
                    "resumed_task_id": existing.get("resumed_task_id"),
                },
            )
        conn.execute(
            """
            UPDATE chat_deferred_reviews
            SET status = 'submitted',
                result_json = ?,
                submitted_at = CURRENT_TIMESTAMP,
                resumed_task_id = ?
            WHERE artifact_ref = ? AND session_id = ? AND vault_name = ?
            """,
            (result_json, resumed_task_id, artifact_ref, session_id, vault_name),
        )
        row = conn.execute(
            """
            SELECT artifact_ref, session_id, vault_name, originating_task_id,
                   status, requests_json, resume_messages_json,
                   resume_config_json, result_json, created_at, submitted_at,
                   resumed_task_id, error_json
            FROM chat_deferred_reviews
            WHERE artifact_ref = ? AND session_id = ? AND vault_name = ?
            """,
            (artifact_ref, session_id, vault_name),
        ).fetchone()
        conn.commit()
    finally:
        conn.close()
    return _review_from_row(row)


def summarize_deferred_review(review: StoredDeferredReview) -> dict[str, Any]:
    """Return compact JSON-safe data suitable for chat task events."""
    approvals = [_tool_call_summary(call) for call in review.requests.approvals]
    calls = [_tool_call_summary(call) for call in review.requests.calls]
    return {
        "artifact_ref": review.artifact_ref,
        "artifact_kind": "deferred_tool_review",
        "status": review.status,
        "review_count": review.review_count,
        "approvals": approvals,
        "calls": calls,
    }


def _review_from_row(row: dict[str, Any]) -> StoredDeferredReview:
    try:
        requests = _DEFERRED_TOOL_REQUESTS_ADAPTER.validate_json(row["requests_json"])
        resume_messages = _MODEL_MESSAGE_LIST_ADAPTER.validate_json(row["resume_messages_json"])
        resume_config = _loads_resume_config(row.get("resume_config_json"))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to deserialize deferred review",
            data={
                "artifact_ref": row.get("artifact_ref"),
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        raise
    return StoredDeferredReview(
        artifact_ref=str(row["artifact_ref"]),
        session_id=str(row["session_id"]),
        vault_name=str(row["vault_name"]),
        originating_task_id=str(row["originating_task_id"]),
        status=str(row["status"]),
        requests=requests,
        resume_messages=list(resume_messages),
        resume_config=resume_config,
        result_json=row.get("result_json"),
        created_at=str(row["created_at"]),
        submitted_at=row.get("submitted_at"),
        resumed_task_id=row.get("resumed_task_id"),
        error_json=row.get("error_json"),
    )


def _tool_call_summary(call: ToolCallPart) -> dict[str, Any]:
    args = call.args
    if isinstance(args, str):
        try:
            parsed_args = json.loads(args)
        except json.JSONDecodeError:
            parsed_args = args
    else:
        parsed_args = args
    return {
        "tool_call_id": call.tool_call_id,
        "tool_name": call.tool_name,
        "args": parsed_args,
    }


def _loads_resume_config(value: Any) -> dict[str, Any]:
    if value in (None, ""):
        return {}
    try:
        loaded = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _tool_names(requests: DeferredToolRequests) -> list[str]:
    names = {
        call.tool_name
        for call in [*requests.approvals, *requests.calls]
        if call.tool_name
    }
    return sorted(names)


def _dict_row_factory(cursor, row) -> dict[str, Any]:
    return {
        column[0]: row[index]
        for index, column in enumerate(cursor.description)
    }
