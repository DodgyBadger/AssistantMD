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
    SQLiteMigration(
        version=2,
        name="multi_google_connections",
        apply=lambda conn: _migrate_google_connections_collection(conn),
    ),
    SQLiteMigration(
        version=3,
        name="google_oauth_generation",
        apply=lambda conn: _add_google_oauth_generation(conn),
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
            _create_current_google_connection_table(conn)
        conn.commit()
    finally:
        conn.close()


def connect_connections(system_root: str | None = None) -> sqlite3.Connection:
    """Open the built-in connections database with named row access."""
    conn = connect_sqlite_from_system_db(DB_NAME, system_root)
    conn.row_factory = sqlite3.Row
    return conn


def _create_google_connection_table(conn: sqlite3.Connection) -> None:
    """Create the v1 singleton table for ordered migration replay."""
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


def _create_current_google_connection_table(conn: sqlite3.Connection) -> None:
    existing_columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(google_connections)")
    }
    if existing_columns and "connection_id" not in existing_columns:
        # Managed startup migrations own conversion of the v1 singleton table.
        return
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS google_connections (
            owner_principal_id TEXT NOT NULL,
            connection_id TEXT NOT NULL,
            slug TEXT NOT NULL,
            display_name TEXT NOT NULL,
            client_id TEXT NOT NULL,
            is_default INTEGER NOT NULL DEFAULT 0,
            gmail_search_default_results INTEGER NOT NULL DEFAULT 20,
            gmail_search_max_results INTEGER NOT NULL DEFAULT 100,
            gmail_message_max_characters INTEGER NOT NULL DEFAULT 50000,
            gmail_thread_max_messages INTEGER NOT NULL DEFAULT 25,
            config_version INTEGER NOT NULL DEFAULT 1,
            oauth_generation INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (owner_principal_id, connection_id),
            UNIQUE (owner_principal_id, slug),
            CHECK (length(owner_principal_id) > 0),
            CHECK (length(connection_id) > 0),
            CHECK (length(slug) > 0),
            CHECK (length(display_name) > 0),
            CHECK (length(client_id) > 0),
            CHECK (is_default IN (0, 1)),
            CHECK (gmail_search_default_results BETWEEN 1 AND 500),
            CHECK (gmail_search_max_results BETWEEN 1 AND 500),
            CHECK (gmail_search_default_results <= gmail_search_max_results),
            CHECK (gmail_message_max_characters BETWEEN 1 AND 250000),
            CHECK (gmail_thread_max_messages BETWEEN 1 AND 100),
            CHECK (config_version > 0),
            CHECK (oauth_generation > 0)
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS google_connections_owner_name_unique
        ON google_connections(owner_principal_id, lower(display_name))
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS google_connections_one_default
        ON google_connections(owner_principal_id) WHERE is_default = 1
        """
    )


def _migrate_google_connections_collection(conn: sqlite3.Connection) -> None:
    columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(google_connections)")
    }
    if "connection_id" in columns:
        _create_current_google_connection_table(conn)
        return
    conn.execute("ALTER TABLE google_connections RENAME TO google_connections_v1")
    _create_current_google_connection_table(conn)
    rows = conn.execute(
        """
        SELECT owner_principal_id, client_id, gmail_search_default_results,
               gmail_search_max_results, gmail_message_max_characters,
               gmail_thread_max_messages, config_version, created_at, updated_at
        FROM google_connections_v1
        """
    ).fetchall()
    for index, row in enumerate(rows):
        owner = str(row[0])
        connection_id = f"legacy-google-{index + 1}-{owner}"
        conn.execute(
            """
            INSERT INTO google_connections (
                owner_principal_id, connection_id, slug, display_name, client_id,
                is_default, gmail_search_default_results,
                gmail_search_max_results, gmail_message_max_characters,
                gmail_thread_max_messages, config_version, created_at, updated_at
            ) VALUES (?, ?, 'google', 'Google', ?, 1, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                owner,
                connection_id,
                row[1],
                row[2],
                row[3],
                row[4],
                row[5],
                row[6],
                row[7],
                row[8],
            ),
        )
    conn.execute("DROP TABLE google_connections_v1")


def _add_google_oauth_generation(conn: sqlite3.Connection) -> None:
    columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(google_connections)")
    }
    if "oauth_generation" not in columns:
        conn.execute(
            """
            ALTER TABLE google_connections
            ADD COLUMN oauth_generation INTEGER NOT NULL DEFAULT 1
            CHECK (oauth_generation > 0)
            """
        )
