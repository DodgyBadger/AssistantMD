"""SQLite schema helpers for session memory."""

from __future__ import annotations

from core.database import connect_sqlite_from_system_db


DB_NAME = "memory"


def ensure_memory_schema(system_root: str | None = None) -> None:
    """Create session memory tables when they do not already exist."""
    conn = connect_sqlite_from_system_db(DB_NAME, system_root)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        _drop_obsolete_memory_tables(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_memories (
                session_id TEXT NOT NULL,
                vault_name TEXT NOT NULL,
                title TEXT,
                summary TEXT,
                domain TEXT,
                work_product TEXT,
                user_intent TEXT,
                named_entities TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                metadata_json TEXT,
                PRIMARY KEY (session_id, vault_name)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_session_memories_vault_updated
            ON session_memories(vault_name, updated_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_session_memories_vault_domain
            ON session_memories(vault_name, domain)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_memory_artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                vault_name TEXT NOT NULL,
                path TEXT NOT NULL,
                artifact_role TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                metadata_json TEXT,
                FOREIGN KEY (session_id, vault_name)
                    REFERENCES session_memories(session_id, vault_name)
                    ON DELETE CASCADE,
                UNIQUE (session_id, vault_name, path, artifact_role)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_session_memory_artifacts_path
            ON session_memory_artifacts(vault_name, path)
            """
        )
        conn.commit()
    finally:
        conn.close()


def _drop_obsolete_memory_tables(conn) -> None:
    """Remove abandoned prototype tables from memory.db."""
    for table_name in (
        "workstream_artifacts",
        "workstream_sessions",
        "workstreams",
        "workstream_field_vectors",
    ):
        conn.execute(f"DROP TABLE IF EXISTS {table_name}")
