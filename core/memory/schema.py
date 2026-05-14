"""SQLite schema helpers for workstream memory."""

from __future__ import annotations

from core.database import connect_sqlite_from_system_db


DB_NAME = "memory"


def ensure_memory_schema(system_root: str | None = None) -> None:
    """Create workstream memory tables when they do not already exist."""
    conn = connect_sqlite_from_system_db(DB_NAME, system_root)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workstreams (
                workstream_id TEXT PRIMARY KEY,
                vault_name TEXT NOT NULL,
                title TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                weight REAL NOT NULL DEFAULT 0,
                confidence REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                metadata_json TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_workstreams_vault_seen
            ON workstreams(vault_name, last_seen_at)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workstream_sessions (
                workstream_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                vault_name TEXT NOT NULL,
                linked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                link_source TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (session_id, vault_name),
                FOREIGN KEY (workstream_id)
                    REFERENCES workstreams(workstream_id)
                    ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_workstream_sessions_workstream
            ON workstream_sessions(workstream_id)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workstream_fields (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workstream_id TEXT NOT NULL,
                field_type TEXT NOT NULL,
                value TEXT NOT NULL,
                normalized_value TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (workstream_id)
                    REFERENCES workstreams(workstream_id)
                    ON DELETE CASCADE,
                UNIQUE (workstream_id, field_type, normalized_value, source)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_workstream_fields_lookup
            ON workstream_fields(field_type, normalized_value)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workstream_artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workstream_id TEXT NOT NULL,
                vault_name TEXT NOT NULL,
                path TEXT NOT NULL,
                artifact_role TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                metadata_json TEXT,
                FOREIGN KEY (workstream_id)
                    REFERENCES workstreams(workstream_id)
                    ON DELETE CASCADE,
                UNIQUE (workstream_id, path, artifact_role, source)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_workstream_artifacts_path
            ON workstream_artifacts(vault_name, path)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workstream_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                current_workstream_id TEXT NOT NULL,
                related_workstream_id TEXT NOT NULL,
                action TEXT NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (current_workstream_id)
                    REFERENCES workstreams(workstream_id)
                    ON DELETE CASCADE,
                FOREIGN KEY (related_workstream_id)
                    REFERENCES workstreams(workstream_id)
                    ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_workstream_feedback_pair
            ON workstream_feedback(current_workstream_id, related_workstream_id, action)
            """
        )
        conn.commit()
    finally:
        conn.close()
