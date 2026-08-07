"""Durable storage for chat inline review requests backed by deferred tools."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import TypeAdapter
from pydantic_ai import DeferredToolRequests, DeferredToolResults
from pydantic_ai.messages import ModelMessage, ToolCallPart

from core.database import connect_sqlite_from_system_db
from core.identity import LOCAL_USER_PRINCIPAL_ID
from core.logger import UnifiedLogger
from core.utils.hash import hash_file_bytes
from core.vault_state.pathing import (
    normalize_vault_relative_path,
    resolve_vault_relative_path,
)

from .schema import DB_NAME, ensure_chat_sessions_schema

logger = UnifiedLogger(tag="chat-deferred-reviews")

_DEFERRED_TOOL_REQUESTS_ADAPTER = TypeAdapter(DeferredToolRequests)
_DEFERRED_TOOL_RESULTS_ADAPTER = TypeAdapter(DeferredToolResults)
_MODEL_MESSAGE_LIST_ADAPTER = TypeAdapter(list[ModelMessage])


class DeferredReviewError(ValueError):
    """Raised when a deferred review cannot be used."""

    def __init__(
        self, code: str, message: str, *, details: dict[str, Any] | None = None
    ):
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
    review_context: dict[str, Any]
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
    review_context: dict[str, Any] | None = None,
) -> StoredDeferredReview:
    """Persist one pending deferred review request and return it."""
    artifact_ref = f"deferred-review-{uuid.uuid4().hex}"
    requests_json = _DEFERRED_TOOL_REQUESTS_ADAPTER.dump_json(requests).decode("utf-8")
    resume_messages_json = _MODEL_MESSAGE_LIST_ADAPTER.dump_json(
        resume_messages
    ).decode("utf-8")
    resume_config_json = json.dumps(resume_config, ensure_ascii=False, sort_keys=True)
    review_context_json = json.dumps(
        review_context or {}, ensure_ascii=False, sort_keys=True
    )

    ensure_chat_sessions_schema()
    conn = connect_sqlite_from_system_db(DB_NAME)
    conn.row_factory = _dict_row_factory
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            INSERT INTO chat_sessions (session_id, vault_name, owner_principal_id)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id, vault_name)
            DO UPDATE SET last_activity_at = CURRENT_TIMESTAMP
            """,
            (session_id, vault_name, LOCAL_USER_PRINCIPAL_ID),
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
                resume_config_json,
                review_context_json
            ) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)
            """,
            (
                artifact_ref,
                session_id,
                vault_name,
                originating_task_id,
                requests_json,
                resume_messages_json,
                resume_config_json,
                review_context_json,
            ),
        )
        row = conn.execute(
            """
            SELECT artifact_ref, session_id, vault_name, originating_task_id,
                   status, requests_json, resume_messages_json,
                   resume_config_json, result_json, created_at, submitted_at,
                   resumed_task_id, error_json, review_context_json
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
                   resumed_task_id, error_json, review_context_json
            FROM chat_deferred_reviews
            WHERE artifact_ref = ? AND session_id = ? AND vault_name = ?
            """,
            (artifact_ref, session_id, vault_name),
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else _review_from_row(row)


def get_pending_deferred_review(
    *, vault_name: str, session_id: str
) -> StoredDeferredReview | None:
    """Return the active pending review for a session, if one exists."""
    ensure_chat_sessions_schema()
    conn = connect_sqlite_from_system_db(DB_NAME)
    conn.row_factory = _dict_row_factory
    try:
        row = conn.execute(
            """
            SELECT artifact_ref, session_id, vault_name, originating_task_id,
                   status, requests_json, resume_messages_json,
                   resume_config_json, result_json, created_at, submitted_at,
                   resumed_task_id, error_json, review_context_json
            FROM chat_deferred_reviews
            WHERE session_id = ? AND vault_name = ? AND status = 'pending'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (session_id, vault_name),
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
    """Atomically claim a pending review before starting its resume task."""
    result_json = _DEFERRED_TOOL_RESULTS_ADAPTER.dump_json(results).decode("utf-8")
    ensure_chat_sessions_schema()
    conn = connect_sqlite_from_system_db(DB_NAME)
    conn.row_factory = _dict_row_factory
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.execute(
            """
            UPDATE chat_deferred_reviews
            SET status = 'resuming',
                result_json = ?,
                submitted_at = CURRENT_TIMESTAMP,
                resumed_task_id = ?
            WHERE artifact_ref = ? AND session_id = ? AND vault_name = ?
              AND status = 'pending'
            """,
            (
                result_json,
                resumed_task_id or None,
                artifact_ref,
                session_id,
                vault_name,
            ),
        )
        if cursor.rowcount != 1:
            existing = conn.execute(
                """
                SELECT artifact_ref, session_id, vault_name, originating_task_id,
                       status, requests_json, resume_messages_json,
                       resume_config_json, result_json, created_at, submitted_at,
                       resumed_task_id, error_json, review_context_json
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
            raise DeferredReviewError(
                "DeferredReviewAlreadySubmitted",
                "Deferred review request has already been submitted.",
                details={
                    "artifact_ref": artifact_ref,
                    "status": str(existing["status"]),
                    "resumed_task_id": existing.get("resumed_task_id"),
                },
            )
        row = conn.execute(
            """
            SELECT artifact_ref, session_id, vault_name, originating_task_id,
                   status, requests_json, resume_messages_json,
                   resume_config_json, result_json, created_at, submitted_at,
                   resumed_task_id, error_json, review_context_json
            FROM chat_deferred_reviews
            WHERE artifact_ref = ? AND session_id = ? AND vault_name = ?
            """,
            (artifact_ref, session_id, vault_name),
        ).fetchone()
        conn.commit()
    finally:
        conn.close()
    review = _review_from_row(row)
    logger.info(
        "chat_deferred_review_claimed",
        data={
            "event": "chat_deferred_review_claimed",
            "artifact_ref": artifact_ref,
            "vault_name": vault_name,
            "session_id": session_id,
        },
    )
    return review


def attach_deferred_review_task(
    *, vault_name: str, session_id: str, artifact_ref: str, resumed_task_id: str
) -> StoredDeferredReview:
    """Attach the created resume task to an atomically claimed review."""
    return _update_deferred_review_state(
        vault_name=vault_name,
        session_id=session_id,
        artifact_ref=artifact_ref,
        expected_statuses=("resuming", "completed", "failed", "cancelled"),
        status="resuming",
        resumed_task_id=resumed_task_id,
        preserve_status=True,
    )


def mark_deferred_review_terminal(
    *,
    vault_name: str,
    session_id: str,
    artifact_ref: str,
    status: str,
    error: dict[str, Any] | None = None,
) -> StoredDeferredReview:
    """Persist the terminal outcome of one resumed review task."""
    if status not in {"completed", "failed", "cancelled"}:
        raise ValueError(f"Invalid deferred review terminal status: {status}")
    review = _update_deferred_review_state(
        vault_name=vault_name,
        session_id=session_id,
        artifact_ref=artifact_ref,
        expected_statuses=("resuming",),
        status=status,
        error=error,
    )
    logger.info(
        "chat_deferred_review_terminal",
        data={
            "event": "chat_deferred_review_terminal",
            "artifact_ref": artifact_ref,
            "vault_name": vault_name,
            "session_id": session_id,
            "status": status,
            "error_type": str((error or {}).get("error_type") or ""),
        },
    )
    return review


def has_pending_deferred_review(*, vault_name: str, session_id: str) -> bool:
    """Return whether a session is paused on an unresolved deferred review."""
    ensure_chat_sessions_schema()
    conn = connect_sqlite_from_system_db(DB_NAME)
    try:
        row = conn.execute(
            """
            SELECT 1 FROM chat_deferred_reviews
            WHERE vault_name = ? AND session_id = ? AND status = 'pending'
            LIMIT 1
            """,
            (vault_name, session_id),
        ).fetchone()
    finally:
        conn.close()
    return row is not None


def capture_deferred_review_context(
    *, vault_path: str, requests: DeferredToolRequests
) -> dict[str, Any]:
    """Capture review-time file facts for destructive existing-file operations."""
    snapshots: dict[str, dict[str, Any]] = {}
    for call in requests.approvals:
        args = call.args_as_dict()
        operation = str(args.get("operation") or "").strip().lower()
        if call.tool_name != "file_write" or operation not in {
            "write",
            "move",
            "delete",
        }:
            continue
        if operation == "write" and not bool(args.get("overwrite")):
            continue
        path = normalize_vault_relative_path(str(args.get("path") or ""))
        if not path:
            continue
        full_path = resolve_vault_relative_path(
            vault_path=vault_path,
            path=path,
            markdown_only=False,
        )
        snapshots[str(call.tool_call_id)] = {
            "path": path,
            "exists": full_path.is_file(),
            "sha256": (
                hash_file_bytes(full_path, length=None) if full_path.is_file() else None
            ),
        }
    return {"file_write_snapshots": snapshots}


def deferred_review_conflicts(
    *, review: StoredDeferredReview, approved_call_ids: set[str], vault_path: str
) -> list[dict[str, Any]]:
    """Return reviewed targets that changed after the review was created."""
    snapshots = review.review_context.get("file_write_snapshots") or {}
    conflicts: list[dict[str, Any]] = []
    for tool_call_id in approved_call_ids:
        snapshot = snapshots.get(tool_call_id)
        if not isinstance(snapshot, dict):
            continue
        path = str(snapshot.get("path") or "")
        full_path = resolve_vault_relative_path(
            vault_path=vault_path,
            path=path,
            markdown_only=False,
        )
        exists = full_path.is_file()
        actual_sha256 = hash_file_bytes(full_path, length=None) if exists else None
        if exists != bool(snapshot.get("exists")) or actual_sha256 != snapshot.get(
            "sha256"
        ):
            conflicts.append(
                {
                    "tool_call_id": tool_call_id,
                    "path": path,
                    "expected_sha256": snapshot.get("sha256"),
                    "actual_sha256": actual_sha256,
                    "expected_exists": bool(snapshot.get("exists")),
                    "actual_exists": exists,
                }
            )
    return conflicts


def _update_deferred_review_state(
    *,
    vault_name: str,
    session_id: str,
    artifact_ref: str,
    expected_statuses: tuple[str, ...],
    status: str,
    resumed_task_id: str | None = None,
    error: dict[str, Any] | None = None,
    preserve_status: bool = False,
) -> StoredDeferredReview:
    ensure_chat_sessions_schema()
    conn = connect_sqlite_from_system_db(DB_NAME)
    conn.row_factory = _dict_row_factory
    try:
        placeholders = ", ".join("?" for _ in expected_statuses)
        cursor = conn.execute(
            f"""
            UPDATE chat_deferred_reviews
            SET status = CASE WHEN ? THEN status ELSE ? END,
                resumed_task_id = COALESCE(?, resumed_task_id),
                error_json = CASE WHEN ? THEN error_json ELSE ? END
            WHERE artifact_ref = ? AND session_id = ? AND vault_name = ?
              AND status IN ({placeholders})
            """,
            (
                preserve_status,
                status,
                resumed_task_id,
                preserve_status,
                (
                    json.dumps(error, ensure_ascii=False, sort_keys=True)
                    if error
                    else None
                ),
                artifact_ref,
                session_id,
                vault_name,
                *expected_statuses,
            ),
        )
        if cursor.rowcount != 1:
            raise DeferredReviewError(
                "DeferredReviewStateConflict",
                "Deferred review state changed before it could be updated.",
                details={"artifact_ref": artifact_ref, "status": status},
            )
        row = conn.execute(
            """
            SELECT artifact_ref, session_id, vault_name, originating_task_id,
                   status, requests_json, resume_messages_json,
                   resume_config_json, result_json, created_at, submitted_at,
                   resumed_task_id, error_json, review_context_json
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
        resume_messages = _MODEL_MESSAGE_LIST_ADAPTER.validate_json(
            row["resume_messages_json"]
        )
        resume_config = _loads_resume_config(row.get("resume_config_json"))
        review_context = _loads_resume_config(row.get("review_context_json"))
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
        review_context=review_context,
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


def _dict_row_factory(cursor: sqlite3.Cursor, row: sqlite3.Row) -> dict[str, Any]:
    return {column[0]: row[index] for index, column in enumerate(cursor.description)}
