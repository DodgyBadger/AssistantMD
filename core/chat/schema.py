"""SQLite schema helpers for durable chat sessions."""

from __future__ import annotations

from core.database import connect_sqlite_from_system_db


DB_NAME = "chat_sessions"


def ensure_chat_sessions_schema(system_root: str | None = None) -> None:
    """Create chat-session tables when they do not already exist."""
    conn = connect_sqlite_from_system_db(DB_NAME, system_root)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_sessions (
                session_id TEXT NOT NULL,
                vault_name TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_activity_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                title TEXT,
                metadata_json TEXT,
                PRIMARY KEY (session_id, vault_name)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                vault_name TEXT NOT NULL,
                sequence_index INTEGER NOT NULL,
                direction TEXT NOT NULL,
                message_type TEXT NOT NULL,
                role TEXT NOT NULL,
                content_text TEXT,
                message_json TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (session_id, vault_name, sequence_index),
                FOREIGN KEY (session_id, vault_name)
                    REFERENCES chat_sessions(session_id, vault_name)
                    ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_messages_session_sequence
            ON chat_messages(session_id, vault_name, sequence_index)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created
            ON chat_messages(session_id, vault_name, created_at)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_tool_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                vault_name TEXT NOT NULL,
                tool_call_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                event_type TEXT NOT NULL,
                args_json TEXT,
                result_text TEXT,
                result_metadata_json TEXT,
                artifact_ref TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id, vault_name)
                    REFERENCES chat_sessions(session_id, vault_name)
                    ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_tool_events_session_created
            ON chat_tool_events(session_id, vault_name, created_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_tool_events_call_id
            ON chat_tool_events(session_id, vault_name, tool_call_id)
            """
        )
        _deduplicate_session_ids(conn)
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_sessions_session_id_unique
            ON chat_sessions(session_id)
            """
        )
        conn.commit()
    finally:
        conn.close()


def _deduplicate_session_ids(conn) -> None:
    """Ensure historical composite-key sessions have globally unique IDs."""
    duplicate_rows = conn.execute(
        """
        SELECT session_id
        FROM chat_sessions
        GROUP BY session_id
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    for (session_id,) in duplicate_rows:
        sessions = conn.execute(
            """
            SELECT rowid, vault_name
            FROM chat_sessions
            WHERE session_id = ?
            ORDER BY created_at ASC, rowid ASC
            """,
            (session_id,),
        ).fetchall()
        for index, (rowid, vault_name) in enumerate(sessions[1:], start=1):
            new_session_id = _deduplicated_session_id(
                conn,
                session_id=str(session_id),
                vault_name=str(vault_name),
                index=index,
            )
            conn.execute(
                """
                UPDATE chat_messages
                SET session_id = ?
                WHERE session_id = ? AND vault_name = ?
                """,
                (new_session_id, session_id, vault_name),
            )
            conn.execute(
                """
                UPDATE chat_tool_events
                SET session_id = ?
                WHERE session_id = ? AND vault_name = ?
                """,
                (new_session_id, session_id, vault_name),
            )
            conn.execute(
                """
                UPDATE chat_sessions
                SET session_id = ?
                WHERE rowid = ?
                """,
                (new_session_id, rowid),
            )


def _deduplicated_session_id(conn, *, session_id: str, vault_name: str, index: int) -> str:
    vault_part = vault_name.strip().replace(" ", "_").replace("/", "_").replace("\\", "_")
    base = f"{session_id}__{vault_part or 'vault'}"
    candidate = base if index == 1 else f"{base}_{index}"
    suffix = index
    while conn.execute(
        "SELECT 1 FROM chat_sessions WHERE session_id = ? LIMIT 1",
        (candidate,),
    ).fetchone():
        suffix += 1
        candidate = f"{base}_{suffix}"
    return candidate
