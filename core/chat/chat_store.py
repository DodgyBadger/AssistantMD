"""Durable SQLite-backed chat session store."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import TypeAdapter
from pydantic_ai.messages import (
    BuiltinToolReturnPart,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from core.database import connect_sqlite_from_system_db
from core.logger import UnifiedLogger

from .schema import DB_NAME, ensure_chat_sessions_schema


logger = UnifiedLogger(tag="chat-store")

_MODEL_MESSAGE_ADAPTER = TypeAdapter(ModelMessage)


@dataclass(frozen=True)
class StoredChatMessage:
    """One stored provider-native chat message."""

    sequence_index: int
    direction: str
    message_type: str
    role: str
    content_text: str
    created_at: str
    message_json: str
    message: ModelMessage


@dataclass(frozen=True)
class StoredChatToolEvent:
    """One stored structured chat tool event."""

    tool_call_id: str
    tool_name: str
    event_type: str
    created_at: str
    args_json: str | None = None
    result_text: str | None = None
    result_metadata_json: str | None = None
    artifact_ref: str | None = None


class ChatStore:
    """Persistent structured chat session store."""

    def __init__(self, system_root: str | None = None):
        self.system_root = system_root
        ensure_chat_sessions_schema(system_root)

    def get_history(self, session_id: str, vault_name: str) -> list[ModelMessage] | None:
        """Return the full provider-native message history for one session."""
        rows = self._fetch_messages(session_id=session_id, vault_name=vault_name)
        if not rows:
            return None
        return [row.message for row in rows]

    def get_stored_messages(
        self,
        session_id: str,
        vault_name: str,
        *,
        limit: int | None = None,
    ) -> list[StoredChatMessage]:
        """Return stored chat messages with persistence metadata."""
        return self._fetch_messages(session_id=session_id, vault_name=vault_name, limit=limit)

    def add_messages(
        self,
        session_id: str,
        vault_name: str,
        messages: list[ModelMessage],
    ) -> None:
        """Append provider-native messages to one session."""
        if not messages:
            return
        conn = self._connect()
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            self._upsert_session(conn, session_id=session_id, vault_name=vault_name)
            next_index = self._next_sequence_index(conn, session_id=session_id, vault_name=vault_name)
            for offset, message in enumerate(messages):
                role, content_text = _extract_role_and_text(message)
                direction = "response" if type(message).__name__ == "ModelResponse" else "request"
                conn.execute(
                    """
                    INSERT INTO chat_messages (
                        session_id,
                        vault_name,
                        sequence_index,
                        direction,
                        message_type,
                        role,
                        content_text,
                        message_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        vault_name,
                        next_index + offset,
                        direction,
                        type(message).__name__,
                        role,
                        content_text,
                        _MODEL_MESSAGE_ADAPTER.dump_json(message).decode("utf-8"),
                    ),
                )
            conn.execute(
                """
                UPDATE chat_sessions
                SET last_activity_at = CURRENT_TIMESTAMP
                WHERE session_id = ? AND vault_name = ?
                """,
                (session_id, vault_name),
            )
            conn.commit()
        finally:
            conn.close()

    def clear_history(self, session_id: str, vault_name: str) -> None:
        """Delete one session and its message history."""
        conn = self._connect()
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                "DELETE FROM chat_sessions WHERE session_id = ? AND vault_name = ?",
                (session_id, vault_name),
            )
            conn.commit()
        finally:
            conn.close()

    def get_message_count(self, session_id: str, vault_name: str) -> int:
        """Return the number of stored messages for one session."""
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT COUNT(*)
                FROM chat_messages
                WHERE session_id = ? AND vault_name = ?
                """,
                (session_id, vault_name),
            ).fetchone()
            return int(row[0] or 0) if row else 0
        finally:
            conn.close()

    def get_recent(self, session_id: str, vault_name: str, limit: int) -> list[ModelMessage]:
        """Return the last N messages in chronological order."""
        if limit <= 0:
            return []
        rows = self._fetch_messages(
            session_id=session_id,
            vault_name=vault_name,
            limit=limit,
        )
        return [row.message for row in rows]

    def get_recent_matching(
        self,
        session_id: str,
        vault_name: str,
        limit: int,
        predicate: Callable[[ModelMessage], bool],
    ) -> list[ModelMessage]:
        """Return the last N matching messages in chronological order."""
        if limit <= 0:
            return []
        history = self.get_history(session_id, vault_name) or []
        matched: list[ModelMessage] = []
        for msg in reversed(history):
            try:
                if predicate(msg):
                    matched.append(msg)
                    if len(matched) >= limit:
                        break
            except Exception:
                continue
        matched.reverse()
        return matched

    def add_tool_event(
        self,
        *,
        session_id: str,
        vault_name: str,
        tool_call_id: str,
        tool_name: str,
        event_type: str,
        args: dict[str, Any] | None = None,
        result_text: str | None = None,
        result_metadata: dict[str, Any] | None = None,
        artifact_ref: str | None = None,
    ) -> None:
        """Persist one structured tool event for a chat session."""
        conn = self._connect()
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            self._upsert_session(conn, session_id=session_id, vault_name=vault_name)
            conn.execute(
                """
                INSERT INTO chat_tool_events (
                    session_id,
                    vault_name,
                    tool_call_id,
                    tool_name,
                    event_type,
                    args_json,
                    result_text,
                    result_metadata_json,
                    artifact_ref
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    vault_name,
                    tool_call_id,
                    tool_name,
                    event_type,
                    None if args is None else json.dumps(args, ensure_ascii=False, sort_keys=True),
                    result_text,
                    None if result_metadata is None else json.dumps(result_metadata, ensure_ascii=False, sort_keys=True),
                    artifact_ref,
                ),
            )
            conn.execute(
                """
                UPDATE chat_sessions
                SET last_activity_at = CURRENT_TIMESTAMP
                WHERE session_id = ? AND vault_name = ?
                """,
                (session_id, vault_name),
            )
            conn.commit()
        finally:
            conn.close()

    def get_tool_events(
        self,
        session_id: str,
        vault_name: str,
        *,
        limit: int | None = None,
    ) -> list[StoredChatToolEvent]:
        """Return persisted structured tool events for one session."""
        conn = self._connect()
        try:
            if limit is None:
                rows = conn.execute(
                    """
                    SELECT tool_call_id, tool_name, event_type, created_at, args_json, result_text, result_metadata_json, artifact_ref
                    FROM chat_tool_events
                    WHERE session_id = ? AND vault_name = ?
                    ORDER BY id ASC
                    """,
                    (session_id, vault_name),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT tool_call_id, tool_name, event_type, created_at, args_json, result_text, result_metadata_json, artifact_ref
                    FROM (
                        SELECT tool_call_id, tool_name, event_type, created_at, args_json, result_text, result_metadata_json, artifact_ref, id
                        FROM chat_tool_events
                        WHERE session_id = ? AND vault_name = ?
                        ORDER BY id DESC
                        LIMIT ?
                    ) recent
                    ORDER BY id ASC
                    """,
                    (session_id, vault_name, limit),
                ).fetchall()
        finally:
            conn.close()

        return [
            StoredChatToolEvent(
                tool_call_id=str(tool_call_id),
                tool_name=str(tool_name),
                event_type=str(event_type),
                created_at=str(created_at or ""),
                args_json=None if args_json is None else str(args_json),
                result_text=None if result_text is None else str(result_text),
                result_metadata_json=None if result_metadata_json is None else str(result_metadata_json),
                artifact_ref=None if artifact_ref is None else str(artifact_ref),
            )
            for (
                tool_call_id,
                tool_name,
                event_type,
                created_at,
                args_json,
                result_text,
                result_metadata_json,
                artifact_ref,
            ) in rows
        ]

    def _fetch_messages(
        self,
        *,
        session_id: str,
        vault_name: str,
        limit: int | None = None,
    ) -> list[StoredChatMessage]:
        conn = self._connect()
        try:
            if limit is None:
                rows = conn.execute(
                    """
                    SELECT sequence_index, direction, message_type, role, content_text, created_at, message_json
                    FROM chat_messages
                    WHERE session_id = ? AND vault_name = ?
                    ORDER BY sequence_index ASC
                    """,
                    (session_id, vault_name),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT sequence_index, direction, message_type, role, content_text, created_at, message_json
                    FROM (
                        SELECT sequence_index, direction, message_type, role, content_text, created_at, message_json
                        FROM chat_messages
                        WHERE session_id = ? AND vault_name = ?
                        ORDER BY sequence_index DESC
                        LIMIT ?
                    ) recent
                    ORDER BY sequence_index ASC
                    """,
                    (session_id, vault_name, limit),
                ).fetchall()
        finally:
            conn.close()

        messages: list[StoredChatMessage] = []
        for row in rows:
            sequence_index, direction, message_type, role, content_text, created_at, message_json = row
            try:
                message = _MODEL_MESSAGE_ADAPTER.validate_json(message_json)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to deserialize stored chat message",
                    metadata={
                        "session_id": session_id,
                        "vault_name": vault_name,
                        "sequence_index": sequence_index,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
                continue
            messages.append(
                StoredChatMessage(
                    sequence_index=int(sequence_index),
                    direction=str(direction),
                    message_type=str(message_type),
                    role=str(role),
                    content_text=str(content_text or ""),
                    created_at=str(created_at or ""),
                    message_json=str(message_json),
                    message=message,
                )
            )
        return messages

    def _connect(self):
        # Re-ensure the schema at call time so long-lived store instances remain
        # correct when the active runtime root changes across validation/system boot.
        ensure_chat_sessions_schema(self.system_root)
        return connect_sqlite_from_system_db(DB_NAME, self.system_root)

    @staticmethod
    def _upsert_session(conn, *, session_id: str, vault_name: str) -> None:
        conn.execute(
            """
            INSERT INTO chat_sessions (session_id, vault_name)
            VALUES (?, ?)
            ON CONFLICT(session_id, vault_name)
            DO UPDATE SET last_activity_at = CURRENT_TIMESTAMP
            """,
            (session_id, vault_name),
        )

    @staticmethod
    def _next_sequence_index(conn, *, session_id: str, vault_name: str) -> int:
        row = conn.execute(
            """
            SELECT COALESCE(MAX(sequence_index), -1) + 1
            FROM chat_messages
            WHERE session_id = ? AND vault_name = ?
            """,
            (session_id, vault_name),
        ).fetchone()
        return int(row[0] or 0) if row else 0


def _extract_role_and_text(msg: ModelMessage) -> tuple[str, str]:
    if isinstance(msg, ModelRequest):
        role = "user"
    elif isinstance(msg, ModelResponse):
        role = "assistant"
    else:
        role = getattr(msg, "role", None) or msg.__class__.__name__.lower()

    parts = getattr(msg, "parts", None)
    if parts:
        has_system_part = False
        rendered_parts: list[str] = []
        for part in parts:
            if isinstance(part, (UserPromptPart, TextPart)):
                part_content = getattr(part, "content", None)
                if isinstance(part_content, str):
                    rendered_parts.append(part_content)
            elif isinstance(part, SystemPromptPart):
                has_system_part = True
                part_content = getattr(part, "content", None)
                if isinstance(part_content, str):
                    rendered_parts.append(part_content)
            elif isinstance(part, (ToolReturnPart, BuiltinToolReturnPart)):
                tool_name = getattr(part, "tool_name", None) or getattr(part, "tool_call_id", None) or "tool"
                part_content = getattr(part, "content", None)
                if isinstance(part_content, str):
                    rendered_parts.append(f"[{tool_name}] {part_content}")
            elif isinstance(part, ToolCallPart):
                tool_name = getattr(part, "tool_name", None) or getattr(part, "tool_call_id", None) or "tool"
                rendered_parts.append(f"[{tool_name}] (tool call)")
        if rendered_parts:
            if has_system_part and role == "user":
                return "system", "\n".join(rendered_parts)
            return role, "\n".join(rendered_parts)

    content = getattr(msg, "content", None)
    if isinstance(content, str) and content:
        return role, content

    return role, ""
