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
                type TEXT,
                topic TEXT,
                entities TEXT,
                project TEXT,
                objective TEXT,
                strategy TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                metadata_json TEXT
            )
            """
        )
        _ensure_workstream_column(conn, "type")
        _ensure_workstream_column(conn, "topic")
        _ensure_workstream_column(conn, "entities")
        _ensure_workstream_column(conn, "project")
        _ensure_workstream_column(conn, "objective")
        _ensure_workstream_column(conn, "strategy")
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_workstreams_vault_seen
            ON workstreams(vault_name, last_seen_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_workstreams_vault_type
            ON workstreams(vault_name, type)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workstream_sessions (
                workstream_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                vault_name TEXT NOT NULL,
                linked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (session_id, vault_name),
                FOREIGN KEY (workstream_id)
                    REFERENCES workstreams(workstream_id)
                    ON DELETE CASCADE
            )
            """
        )
        _rebuild_table_if_columns_present(
            conn,
            table_name="workstream_sessions",
            obsolete_columns={"link_source", "confidence"},
            create_sql="""
                CREATE TABLE workstream_sessions (
                    workstream_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    vault_name TEXT NOT NULL,
                    linked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (session_id, vault_name),
                    FOREIGN KEY (workstream_id)
                        REFERENCES workstreams(workstream_id)
                        ON DELETE CASCADE
                )
            """,
            copy_columns=("workstream_id", "session_id", "vault_name", "linked_at"),
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_workstream_sessions_workstream
            ON workstream_sessions(workstream_id)
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
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                metadata_json TEXT,
                FOREIGN KEY (workstream_id)
                    REFERENCES workstreams(workstream_id)
                    ON DELETE CASCADE,
                UNIQUE (workstream_id, path, artifact_role)
            )
            """
        )
        _rebuild_table_if_columns_present(
            conn,
            table_name="workstream_artifacts",
            obsolete_columns={"source"},
            create_sql="""
                CREATE TABLE workstream_artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workstream_id TEXT NOT NULL,
                    vault_name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    artifact_role TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    metadata_json TEXT,
                    FOREIGN KEY (workstream_id)
                        REFERENCES workstreams(workstream_id)
                        ON DELETE CASCADE,
                    UNIQUE (workstream_id, path, artifact_role)
                )
            """,
            copy_columns=(
                "id",
                "workstream_id",
                "vault_name",
                "path",
                "artifact_role",
                "created_at",
                "metadata_json",
            ),
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_workstream_artifacts_path
            ON workstream_artifacts(vault_name, path)
            """
        )
        conn.commit()
    finally:
        conn.close()


def _ensure_workstream_column(conn, column_name: str) -> None:
    existing = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(workstreams)").fetchall()
    }
    if column_name not in existing:
        conn.execute(f"ALTER TABLE workstreams ADD COLUMN {column_name} TEXT")


def _rebuild_table_if_columns_present(
    conn,
    *,
    table_name: str,
    obsolete_columns: set[str],
    create_sql: str,
    copy_columns: tuple[str, ...],
) -> None:
    existing = {
        str(row[1])
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if not existing.intersection(obsolete_columns):
        return
    temp_table = f"{table_name}_new"
    conn.execute(f"DROP TABLE IF EXISTS {temp_table}")
    conn.execute(create_sql.replace(table_name, temp_table, 1))
    columns = ", ".join(copy_columns)
    conn.execute(
        f"""
        INSERT OR IGNORE INTO {temp_table} ({columns})
        SELECT {columns}
        FROM {table_name}
        """
    )
    conn.execute(f"DROP TABLE {table_name}")
    conn.execute(f"ALTER TABLE {temp_table} RENAME TO {table_name}")
