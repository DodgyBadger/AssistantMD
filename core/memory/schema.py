"""SQLite schema helpers for work episode memory."""

from __future__ import annotations

from core.database import connect_sqlite_from_system_db


DB_NAME = "memory"


def ensure_memory_schema(system_root: str | None = None) -> None:
    """Create work episode memory tables when they do not already exist."""
    conn = connect_sqlite_from_system_db(DB_NAME, system_root)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS work_episodes (
                episode_id TEXT PRIMARY KEY,
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
            CREATE INDEX IF NOT EXISTS idx_work_episodes_vault_seen
            ON work_episodes(vault_name, last_seen_at)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS work_episode_sessions (
                episode_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                vault_name TEXT NOT NULL,
                linked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                link_source TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (session_id, vault_name),
                FOREIGN KEY (episode_id)
                    REFERENCES work_episodes(episode_id)
                    ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_work_episode_sessions_episode
            ON work_episode_sessions(episode_id)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS work_episode_fields (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                episode_id TEXT NOT NULL,
                field_type TEXT NOT NULL,
                value TEXT NOT NULL,
                normalized_value TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (episode_id)
                    REFERENCES work_episodes(episode_id)
                    ON DELETE CASCADE,
                UNIQUE (episode_id, field_type, normalized_value, source)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_work_episode_fields_lookup
            ON work_episode_fields(field_type, normalized_value)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS work_episode_artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                episode_id TEXT NOT NULL,
                vault_name TEXT NOT NULL,
                path TEXT NOT NULL,
                artifact_role TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                metadata_json TEXT,
                FOREIGN KEY (episode_id)
                    REFERENCES work_episodes(episode_id)
                    ON DELETE CASCADE,
                UNIQUE (episode_id, path, artifact_role, source)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_work_episode_artifacts_path
            ON work_episode_artifacts(vault_name, path)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS work_episode_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                current_episode_id TEXT NOT NULL,
                related_episode_id TEXT NOT NULL,
                action TEXT NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (current_episode_id)
                    REFERENCES work_episodes(episode_id)
                    ON DELETE CASCADE,
                FOREIGN KEY (related_episode_id)
                    REFERENCES work_episodes(episode_id)
                    ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_work_episode_feedback_pair
            ON work_episode_feedback(current_episode_id, related_episode_id, action)
            """
        )
        conn.commit()
    finally:
        conn.close()
