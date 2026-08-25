"""SQLite schema for principal-owned built-in connections."""

from __future__ import annotations

import sqlite3

from core.database import connect_sqlite_from_system_db
from core.database_migrations import SQLiteMigration, apply_sqlite_migrations

DB_NAME = "connections"
MIGRATION_NAMESPACE = "connections"
CONNECTION_MIGRATIONS = (
    SQLiteMigration(
        version=1,
        name="principal_owned_google_connection",
        apply=lambda conn: _create_google_connection_table(conn),
    ),
)


def ensure_connections_schema(
    system_root: str | None = None, *, apply_migrations: bool = False
) -> None:
    """Create the current built-in connections schema."""
    conn = connect_sqlite_from_system_db(DB_NAME, system_root)
    try:
        if apply_migrations:
            apply_sqlite_migrations(
                conn,
                namespace=MIGRATION_NAMESPACE,
                migrations=CONNECTION_MIGRATIONS,
            )
        else:
            _create_google_connection_table(conn)
        conn.commit()
    finally:
        conn.close()


def connect_connections(system_root: str | None = None) -> sqlite3.Connection:
    """Open the built-in connections database with named row access."""
    conn = connect_sqlite_from_system_db(DB_NAME, system_root)
    conn.row_factory = sqlite3.Row
    return conn


def _create_google_connection_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS google_connections (
            owner_principal_id TEXT PRIMARY KEY,
            client_id TEXT NOT NULL,
            gmail_search_default_results INTEGER NOT NULL DEFAULT 20,
            gmail_search_max_results INTEGER NOT NULL DEFAULT 100,
            gmail_message_max_characters INTEGER NOT NULL DEFAULT 50000,
            gmail_thread_max_messages INTEGER NOT NULL DEFAULT 25,
            config_version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK (length(owner_principal_id) > 0),
            CHECK (length(client_id) > 0),
            CHECK (gmail_search_default_results BETWEEN 1 AND 500),
            CHECK (gmail_search_max_results BETWEEN 1 AND 500),
            CHECK (gmail_search_default_results <= gmail_search_max_results),
            CHECK (gmail_message_max_characters BETWEEN 1 AND 250000),
            CHECK (gmail_thread_max_messages BETWEEN 1 AND 100),
            CHECK (config_version > 0)
        )
        """
    )
