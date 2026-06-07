"""Durable SQLite-backed chat session store."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Literal

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
_MODEL_MESSAGE_LIST_ADAPTER = TypeAdapter(list[ModelMessage])
HistoryMode = Literal["effective", "raw"]


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
class StoredCompactionCheckpoint:
    """One stored chat compaction checkpoint."""

    id: int
    checkpoint_id: str
    session_id: str
    vault_name: str
    created_at: str
    source: str
    message_count_before: int
    last_message_sequence_index: int
    summary_message_json: str
    replacement_history_json: str
    metadata_json: str | None = None


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


@dataclass(frozen=True)
class StoredChatSession:
    """One stored chat session summary."""

    session_id: str
    vault_name: str
    created_at: str
    last_activity_at: str
    title: str | None = None
    metadata_json: str | None = None


class ChatStore:
    """Persistent structured chat session store."""

    def __init__(self, system_root: str | None = None):
        self.system_root = system_root
        ensure_chat_sessions_schema(system_root)

    def get_history(
        self,
        session_id: str,
        vault_name: str,
        *,
        mode: HistoryMode = "effective",
    ) -> list[ModelMessage] | None:
        """Return provider-native message history for one session."""
        rows = self._fetch_messages(
            session_id=session_id,
            vault_name=vault_name,
            mode=mode,
        )
        if not rows:
            return None
        return [row.message for row in rows]

    def get_stored_messages(
        self,
        session_id: str,
        vault_name: str,
        *,
        limit: int | None = None,
        mode: HistoryMode = "effective",
    ) -> list[StoredChatMessage]:
        """Return stored chat messages with persistence metadata."""
        return self._fetch_messages(
            session_id=session_id,
            vault_name=vault_name,
            limit=limit,
            mode=mode,
        )

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
            self._touch_session(
                conn,
                session_id=session_id,
                vault_name=vault_name,
                advance_history_revision=True,
            )
            conn.commit()
        finally:
            conn.close()

    def ensure_session(self, session_id: str, vault_name: str) -> StoredChatSession:
        """Create or touch a session bound to one vault, returning its summary."""
        conn = self._connect()
        try:
            self._upsert_session(conn, session_id=session_id, vault_name=vault_name)
            conn.commit()
        finally:
            conn.close()
        session = self.get_session(session_id=session_id, vault_name=vault_name)
        if session is None:  # pragma: no cover - defensive consistency check
            raise RuntimeError(f"Failed to create chat session '{session_id}'.")
        return session

    def replace_session_messages(
        self,
        session_id: str,
        vault_name: str,
        messages: list[ModelMessage],
        *,
        metadata_update: dict[str, Any] | None = None,
    ) -> None:
        """Replace one session's canonical messages in a single transaction."""
        conn = self._connect()
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            self._upsert_session(conn, session_id=session_id, vault_name=vault_name)
            conn.execute(
                """
                DELETE FROM chat_compaction_checkpoints
                WHERE session_id = ? AND vault_name = ?
                """,
                (session_id, vault_name),
            )
            conn.execute(
                """
                DELETE FROM chat_messages
                WHERE session_id = ? AND vault_name = ?
                """,
                (session_id, vault_name),
            )
            for sequence_index, message in enumerate(messages):
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
                        sequence_index,
                        direction,
                        type(message).__name__,
                        role,
                        content_text,
                        _MODEL_MESSAGE_ADAPTER.dump_json(message).decode("utf-8"),
                    ),
                )
            self._touch_session(
                conn,
                session_id=session_id,
                vault_name=vault_name,
                metadata_update=metadata_update,
                advance_history_revision=True,
            )
            conn.commit()
        finally:
            conn.close()

    def fork_session(
        self,
        *,
        source_session_id: str,
        new_session_id: str,
        vault_name: str,
        through_sequence_index: int,
        title: str | None,
        metadata_update: dict[str, Any] | None = None,
    ) -> int:
        """Create a new session from one source session's raw message prefix."""
        conn = self._connect()
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            source = conn.execute(
                """
                SELECT metadata_json
                FROM chat_sessions
                WHERE session_id = ? AND vault_name = ?
                """,
                (source_session_id, vault_name),
            ).fetchone()
            if source is None:
                raise ValueError(f"Chat session not found: {source_session_id}")

            source_metadata: dict[str, Any] = {}
            if source[0]:
                try:
                    parsed_metadata = json.loads(str(source[0]))
                    if isinstance(parsed_metadata, dict):
                        source_metadata = parsed_metadata
                except Exception:
                    source_metadata = {}
            if metadata_update:
                source_metadata.update(metadata_update)

            source_rows = conn.execute(
                """
                SELECT sequence_index, direction, message_type, role, content_text, message_json
                FROM chat_messages
                WHERE session_id = ? AND vault_name = ?
                ORDER BY sequence_index ASC
                """,
                (source_session_id, vault_name),
            ).fetchall()
            rows = _fork_prefix_rows(source_rows, through_sequence_index)
            if not rows:
                raise ValueError(
                    f"No chat messages found through sequence {through_sequence_index}"
                )

            conn.execute(
                """
                INSERT INTO chat_sessions (
                    session_id,
                    vault_name,
                    title,
                    metadata_json
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    new_session_id,
                    vault_name,
                    title or None,
                    json.dumps(source_metadata, ensure_ascii=False, sort_keys=True),
                ),
            )

            copied_tool_call_ids: set[str] = set()
            for new_sequence_index, row in enumerate(rows):
                _sequence_index, direction, message_type, role, content_text, message_json = row
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
                        new_session_id,
                        vault_name,
                        new_sequence_index,
                        direction,
                        message_type,
                        role,
                        content_text,
                        message_json,
                    ),
                )
                copied_tool_call_ids.update(_tool_call_ids_from_json(str(message_json)))

            if copied_tool_call_ids:
                event_rows = conn.execute(
                    """
                    SELECT tool_call_id, tool_name, event_type, args_json, result_text,
                           result_metadata_json, artifact_ref
                    FROM chat_tool_events
                    WHERE session_id = ? AND vault_name = ?
                    ORDER BY id ASC
                    """,
                    (source_session_id, vault_name),
                ).fetchall()
                for event_row in event_rows:
                    (
                        tool_call_id,
                        tool_name,
                        event_type,
                        args_json,
                        result_text,
                        result_metadata_json,
                        artifact_ref,
                    ) = event_row
                    if str(tool_call_id) not in copied_tool_call_ids:
                        continue
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
                            new_session_id,
                            vault_name,
                            tool_call_id,
                            tool_name,
                            event_type,
                            args_json,
                            result_text,
                            result_metadata_json,
                            artifact_ref,
                        ),
                    )

            self._touch_session(
                conn,
                session_id=new_session_id,
                vault_name=vault_name,
                advance_history_revision=True,
            )
            conn.commit()
            return len(rows)
        finally:
            conn.close()

    def set_session_title(self, session_id: str, vault_name: str, title: str | None) -> None:
        """Set or clear the user-defined title for a session."""
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE chat_sessions SET title = ? WHERE session_id = ? AND vault_name = ?",
                (title or None, session_id, vault_name),
            )
            conn.commit()
        finally:
            conn.close()

    def delete_sessions(
        self,
        vault_name: str,
        *,
        session_id: str | None = None,
        older_than_days: int | None = None,
    ) -> list[str]:
        """Delete sessions for a vault, returning the list of deleted session_ids.

        - session_id: delete exactly one session by ID
        - older_than_days: delete sessions older than N days
        - neither: delete all sessions for the vault

        CASCADE deletes handle messages and tool_events automatically.
        """
        conn = self._connect()
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            if session_id is not None:
                rows = conn.execute(
                    "SELECT session_id FROM chat_sessions WHERE session_id = ? AND vault_name = ?",
                    (session_id, vault_name),
                ).fetchall()
                conn.execute(
                    "DELETE FROM chat_sessions WHERE session_id = ? AND vault_name = ?",
                    (session_id, vault_name),
                )
            elif older_than_days is not None:
                rows = conn.execute(
                    """
                    SELECT session_id FROM chat_sessions
                    WHERE vault_name = ?
                    AND last_activity_at < datetime('now', ? || ' days')
                    """,
                    (vault_name, f"-{older_than_days}"),
                ).fetchall()
                conn.execute(
                    """
                    DELETE FROM chat_sessions
                    WHERE vault_name = ?
                    AND last_activity_at < datetime('now', ? || ' days')
                    """,
                    (vault_name, f"-{older_than_days}"),
                )
            else:
                rows = conn.execute(
                    "SELECT session_id FROM chat_sessions WHERE vault_name = ?",
                    (vault_name,),
                ).fetchall()
                conn.execute(
                    "DELETE FROM chat_sessions WHERE vault_name = ?",
                    (vault_name,),
                )
            conn.commit()
        finally:
            conn.close()
        return [str(row[0]) for row in rows]

    def get_message_count(
        self,
        session_id: str,
        vault_name: str,
        *,
        mode: HistoryMode = "effective",
    ) -> int:
        """Return the number of messages for one session."""
        _validate_history_mode(mode)
        if mode == "effective":
            return len(self.get_stored_messages(session_id, vault_name))
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

    def get_recent(
        self,
        session_id: str,
        vault_name: str,
        limit: int,
        *,
        mode: HistoryMode = "effective",
    ) -> list[ModelMessage]:
        """Return the last N messages in chronological order."""
        if limit <= 0:
            return []
        rows = self._fetch_messages(
            session_id=session_id,
            vault_name=vault_name,
            limit=limit,
            mode=mode,
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
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Message predicate raised in get_recent_matching",
                    data={"session_id": session_id, "vault_name": vault_name, "error": str(exc)},
                )
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
            self._touch_session(conn, session_id=session_id, vault_name=vault_name)
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

    def list_sessions(self, vault_name: str, *, limit: int | None = None) -> list[StoredChatSession]:
        """Return chat sessions for one vault ordered by latest activity descending."""
        conn = self._connect()
        try:
            if limit is None:
                rows = conn.execute(
                    """
                    SELECT session_id, vault_name, created_at, last_activity_at, title, metadata_json
                    FROM chat_sessions
                    WHERE vault_name = ?
                    ORDER BY last_activity_at DESC, created_at DESC, session_id DESC
                    """,
                    (vault_name,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT session_id, vault_name, created_at, last_activity_at, title, metadata_json
                    FROM chat_sessions
                    WHERE vault_name = ?
                    ORDER BY last_activity_at DESC, created_at DESC, session_id DESC
                    LIMIT ?
                    """,
                    (vault_name, limit),
                ).fetchall()
        finally:
            conn.close()

        return [
            StoredChatSession(
                session_id=str(session_id),
                vault_name=str(session_vault_name),
                created_at=str(created_at or ""),
                last_activity_at=str(last_activity_at or ""),
                title=None if title is None else str(title),
                metadata_json=None if metadata_json is None else str(metadata_json),
            )
            for session_id, session_vault_name, created_at, last_activity_at, title, metadata_json in rows
        ]

    def get_session(self, session_id: str, vault_name: str) -> StoredChatSession | None:
        """Return one stored chat session summary, if present."""
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT session_id, vault_name, created_at, last_activity_at, title, metadata_json
                FROM chat_sessions
                WHERE session_id = ? AND vault_name = ?
                """,
                (session_id, vault_name),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        session_id_value, session_vault_name, created_at, last_activity_at, title, metadata_json = row
        return StoredChatSession(
            session_id=str(session_id_value),
            vault_name=str(session_vault_name),
            created_at=str(created_at or ""),
            last_activity_at=str(last_activity_at or ""),
            title=None if title is None else str(title),
            metadata_json=None if metadata_json is None else str(metadata_json),
        )

    def get_session_by_id(self, session_id: str) -> StoredChatSession | None:
        """Return one stored chat session by globally unique session ID."""
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT session_id, vault_name, created_at, last_activity_at, title, metadata_json
                FROM chat_sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        session_id_value, session_vault_name, created_at, last_activity_at, title, metadata_json = row
        return StoredChatSession(
            session_id=str(session_id_value),
            vault_name=str(session_vault_name),
            created_at=str(created_at or ""),
            last_activity_at=str(last_activity_at or ""),
            title=None if title is None else str(title),
            metadata_json=None if metadata_json is None else str(metadata_json),
        )

    def get_session_metadata(self, session_id: str, vault_name: str) -> dict[str, Any]:
        """Return parsed session metadata, ignoring malformed stored JSON."""
        session = self.get_session(session_id, vault_name)
        if session is None or not session.metadata_json:
            return {}
        try:
            parsed = json.loads(session.metadata_json)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def set_session_workspace(
        self,
        *,
        session_id: str,
        vault_name: str,
        workspace_path: str | None,
    ) -> None:
        """Set or clear the workspace path stored in session metadata."""
        conn = self._connect()
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            self._upsert_session(conn, session_id=session_id, vault_name=vault_name)
            metadata = self._session_metadata(
                conn,
                session_id=session_id,
                vault_name=vault_name,
            )
            normalized_path = (workspace_path or "").strip()
            if normalized_path:
                metadata["workspace"] = {"path": normalized_path}
            else:
                metadata.pop("workspace", None)
            conn.execute(
                """
                UPDATE chat_sessions
                SET last_activity_at = CURRENT_TIMESTAMP, metadata_json = ?
                WHERE session_id = ? AND vault_name = ?
                """,
                (
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    session_id,
                    vault_name,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_session_workspace_path(self, session_id: str, vault_name: str) -> str:
        """Return the stored workspace path for one session, if set."""
        metadata = self.get_session_metadata(session_id, vault_name)
        workspace = metadata.get("workspace")
        if not isinstance(workspace, dict):
            return ""
        path = workspace.get("path")
        return str(path).strip() if path is not None else ""

    def get_session_history_revision(self, session_id: str, vault_name: str) -> int:
        """Return the monotonic effective-history revision for one session."""
        return _metadata_history_revision(self.get_session_metadata(session_id, vault_name))

    def get_latest_compaction_checkpoint(
        self,
        session_id: str,
        vault_name: str,
    ) -> StoredCompactionCheckpoint | None:
        """Return the latest compaction checkpoint for one session."""
        conn = self._connect()
        try:
            checkpoint = self._latest_compaction_checkpoint(
                conn,
                session_id=session_id,
                vault_name=vault_name,
            )
        finally:
            conn.close()
        return checkpoint

    def get_highest_message_sequence_index(self, session_id: str, vault_name: str) -> int:
        """Return the current raw message high-water mark for one session."""
        conn = self._connect()
        try:
            return self._highest_message_sequence_index(
                conn,
                session_id=session_id,
                vault_name=vault_name,
            )
        finally:
            conn.close()

    def add_compaction_checkpoint(
        self,
        *,
        session_id: str,
        vault_name: str,
        checkpoint_id: str,
        source: str,
        message_count_before: int,
        last_message_sequence_index: int,
        summary_message: ModelMessage,
        replacement_history: list[ModelMessage],
        metadata: dict[str, Any] | None = None,
        metadata_update: dict[str, Any] | None = None,
    ) -> None:
        """Record a compaction checkpoint without mutating raw chat messages."""
        conn = self._connect()
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            self._upsert_session(conn, session_id=session_id, vault_name=vault_name)
            conn.execute(
                """
                INSERT INTO chat_compaction_checkpoints (
                    checkpoint_id,
                    session_id,
                    vault_name,
                    source,
                    message_count_before,
                    last_message_sequence_index,
                    summary_message_json,
                    replacement_history_json,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    checkpoint_id,
                    session_id,
                    vault_name,
                    source,
                    message_count_before,
                    last_message_sequence_index,
                    _MODEL_MESSAGE_ADAPTER.dump_json(summary_message).decode("utf-8"),
                    _MODEL_MESSAGE_LIST_ADAPTER.dump_json(replacement_history).decode("utf-8"),
                    None if metadata is None else json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                ),
            )
            self._touch_session(
                conn,
                session_id=session_id,
                vault_name=vault_name,
                metadata_update=metadata_update,
                advance_history_revision=True,
            )
            conn.commit()
        finally:
            conn.close()

    def _fetch_messages(
        self,
        *,
        session_id: str,
        vault_name: str,
        limit: int | None = None,
        mode: HistoryMode = "effective",
    ) -> list[StoredChatMessage]:
        _validate_history_mode(mode)
        conn = self._connect()
        try:
            if mode == "raw":
                return self._fetch_raw_messages_from_conn(
                    conn,
                    session_id=session_id,
                    vault_name=vault_name,
                    limit=limit,
                )
            return self._fetch_effective_messages_from_conn(
                conn,
                session_id=session_id,
                vault_name=vault_name,
                limit=limit,
            )
        finally:
            conn.close()

    def _fetch_effective_messages_from_conn(
        self,
        conn,
        *,
        session_id: str,
        vault_name: str,
        limit: int | None = None,
    ) -> list[StoredChatMessage]:
        checkpoint = self._latest_compaction_checkpoint(
            conn,
            session_id=session_id,
            vault_name=vault_name,
        )
        if checkpoint is None:
            return self._fetch_raw_messages_from_conn(
                conn,
                session_id=session_id,
                vault_name=vault_name,
                limit=limit,
            )
        replacement = self._checkpoint_replacement_messages(
            checkpoint,
            session_id=session_id,
            vault_name=vault_name,
        )
        raw_after = self._fetch_raw_messages_from_conn(
            conn,
            session_id=session_id,
            vault_name=vault_name,
            after_sequence_index=checkpoint.last_message_sequence_index,
        )
        messages = [*replacement, *raw_after]
        if limit is not None:
            messages = messages[-limit:]
        return messages

    def _fetch_raw_messages_from_conn(
        self,
        conn,
        *,
        session_id: str,
        vault_name: str,
        limit: int | None = None,
        after_sequence_index: int | None = None,
    ) -> list[StoredChatMessage]:
        sequence_filter = ""
        params: list[Any] = [session_id, vault_name]
        if after_sequence_index is not None:
            sequence_filter = "AND sequence_index > ?"
            params.append(after_sequence_index)

        if limit is None:
            rows = conn.execute(
                f"""
                SELECT sequence_index, direction, message_type, role, content_text, created_at, message_json
                FROM chat_messages
                WHERE session_id = ? AND vault_name = ?
                {sequence_filter}
                ORDER BY sequence_index ASC
                """,
                params,
            ).fetchall()
        else:
            params.append(limit)
            rows = conn.execute(
                f"""
                SELECT sequence_index, direction, message_type, role, content_text, created_at, message_json
                FROM (
                    SELECT sequence_index, direction, message_type, role, content_text, created_at, message_json
                    FROM chat_messages
                    WHERE session_id = ? AND vault_name = ?
                    {sequence_filter}
                    ORDER BY sequence_index DESC
                    LIMIT ?
                ) recent
                ORDER BY sequence_index ASC
                """,
                params,
            ).fetchall()
        return self._stored_messages_from_rows(
            rows,
            session_id=session_id,
            vault_name=vault_name,
        )

    def _checkpoint_replacement_messages(
        self,
        checkpoint: StoredCompactionCheckpoint,
        *,
        session_id: str,
        vault_name: str,
    ) -> list[StoredChatMessage]:
        try:
            messages = _MODEL_MESSAGE_LIST_ADAPTER.validate_json(checkpoint.replacement_history_json)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to deserialize compaction checkpoint replacement history",
                data={
                    "session_id": session_id,
                    "vault_name": vault_name,
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            return []

        stored_messages: list[StoredChatMessage] = []
        for sequence_index, message in enumerate(messages):
            role, content_text = _extract_role_and_text(message)
            direction = "response" if type(message).__name__ == "ModelResponse" else "request"
            stored_messages.append(
                StoredChatMessage(
                    sequence_index=sequence_index,
                    direction=direction,
                    message_type=type(message).__name__,
                    role=role,
                    content_text=content_text,
                    created_at=checkpoint.created_at,
                    message_json=_MODEL_MESSAGE_ADAPTER.dump_json(message).decode("utf-8"),
                    message=message,
                )
            )
        return stored_messages

    def _stored_messages_from_rows(
        self,
        rows,
        *,
        session_id: str,
        vault_name: str,
    ) -> list[StoredChatMessage]:
        messages: list[StoredChatMessage] = []
        for row in rows:
            sequence_index, direction, message_type, role, content_text, created_at, message_json = row
            try:
                message = _MODEL_MESSAGE_ADAPTER.validate_json(message_json)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to deserialize stored chat message",
                    data={
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

    @staticmethod
    def _latest_compaction_checkpoint(
        conn,
        *,
        session_id: str,
        vault_name: str,
    ) -> StoredCompactionCheckpoint | None:
        row = conn.execute(
            """
            SELECT id, checkpoint_id, session_id, vault_name, created_at, source,
                   message_count_before, last_message_sequence_index,
                   summary_message_json, replacement_history_json, metadata_json
            FROM chat_compaction_checkpoints
            WHERE session_id = ? AND vault_name = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (session_id, vault_name),
        ).fetchone()
        if row is None:
            return None
        (
            row_id,
            checkpoint_id,
            row_session_id,
            row_vault_name,
            created_at,
            source,
            message_count_before,
            last_message_sequence_index,
            summary_message_json,
            replacement_history_json,
            metadata_json,
        ) = row
        return StoredCompactionCheckpoint(
            id=int(row_id),
            checkpoint_id=str(checkpoint_id),
            session_id=str(row_session_id),
            vault_name=str(row_vault_name),
            created_at=str(created_at or ""),
            source=str(source),
            message_count_before=int(message_count_before),
            last_message_sequence_index=int(last_message_sequence_index),
            summary_message_json=str(summary_message_json),
            replacement_history_json=str(replacement_history_json),
            metadata_json=None if metadata_json is None else str(metadata_json),
        )

    @staticmethod
    def _highest_message_sequence_index(conn, *, session_id: str, vault_name: str) -> int:
        row = conn.execute(
            """
            SELECT COALESCE(MAX(sequence_index), -1)
            FROM chat_messages
            WHERE session_id = ? AND vault_name = ?
            """,
            (session_id, vault_name),
        ).fetchone()
        return int(row[0] if row else -1)

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
    def _touch_session(
        conn,
        *,
        session_id: str,
        vault_name: str,
        metadata_update: dict[str, Any] | None = None,
        advance_history_revision: bool = False,
    ) -> None:
        if metadata_update or advance_history_revision:
            metadata = ChatStore._session_metadata(
                conn,
                session_id=session_id,
                vault_name=vault_name,
            )
            if metadata_update:
                metadata.update(metadata_update)
            if advance_history_revision:
                metadata["history_revision"] = _metadata_history_revision(metadata) + 1
            conn.execute(
                """
                UPDATE chat_sessions
                SET last_activity_at = CURRENT_TIMESTAMP, metadata_json = ?
                WHERE session_id = ? AND vault_name = ?
                """,
                (json.dumps(metadata, ensure_ascii=False, sort_keys=True), session_id, vault_name),
            )
            return
        conn.execute(
            """
            UPDATE chat_sessions
            SET last_activity_at = CURRENT_TIMESTAMP
            WHERE session_id = ? AND vault_name = ?
            """,
            (session_id, vault_name),
        )

    @staticmethod
    def _session_metadata(conn, *, session_id: str, vault_name: str) -> dict[str, Any]:
        row = conn.execute(
            """
            SELECT metadata_json
            FROM chat_sessions
            WHERE session_id = ? AND vault_name = ?
            """,
            (session_id, vault_name),
        ).fetchone()
        metadata: dict[str, Any] = {}
        if row and row[0]:
            try:
                parsed = json.loads(str(row[0]))
                if isinstance(parsed, dict):
                    metadata = parsed
            except Exception:
                metadata = {}
        return metadata

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

    @staticmethod
    def _merged_session_metadata_json(
        conn,
        *,
        session_id: str,
        vault_name: str,
        metadata_update: dict[str, Any],
    ) -> str:
        metadata = ChatStore._session_metadata(
            conn,
            session_id=session_id,
            vault_name=vault_name,
        )
        metadata.update(metadata_update)
        return json.dumps(metadata, ensure_ascii=False, sort_keys=True)


def _validate_history_mode(mode: str) -> None:
    if mode not in {"effective", "raw"}:
        raise ValueError("history mode must be one of: effective, raw")


def _metadata_history_revision(metadata: dict[str, Any]) -> int:
    raw = metadata.get("history_revision")
    try:
        revision = int(raw)
    except (TypeError, ValueError):
        return 0
    return max(revision, 0)


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


def _fork_prefix_rows(rows: list[Any], through_sequence_index: int) -> list[Any]:
    copied: list[Any] = []
    pending_tool_call_ids: set[str] = set()
    for row in rows:
        sequence_index = int(row[0])
        if sequence_index > through_sequence_index and not pending_tool_call_ids:
            break
        copied.append(row)
        message_json = str(row[5])
        pending_tool_call_ids.update(_tool_call_ids_from_json(message_json))
        pending_tool_call_ids.difference_update(_tool_return_ids_from_json(message_json))
    return copied


def _tool_call_ids_from_json(message_json: str) -> set[str]:
    try:
        message = _MODEL_MESSAGE_ADAPTER.validate_json(message_json)
    except Exception:
        return set()
    return _tool_call_ids_from_message(message)


def _tool_call_ids_from_message(message: ModelMessage) -> set[str]:
    ids: set[str] = set()
    for part in getattr(message, "parts", ()) or ():
        if isinstance(part, ToolCallPart):
            tool_call_id = getattr(part, "tool_call_id", None)
            if tool_call_id:
                ids.add(str(tool_call_id))
    return ids


def _tool_return_ids_from_json(message_json: str) -> set[str]:
    try:
        message = _MODEL_MESSAGE_ADAPTER.validate_json(message_json)
    except Exception:
        return set()
    ids: set[str] = set()
    for part in getattr(message, "parts", ()) or ():
        if isinstance(part, (ToolReturnPart, BuiltinToolReturnPart)):
            tool_call_id = getattr(part, "tool_call_id", None)
            if tool_call_id:
                ids.add(str(tool_call_id))
    return ids
