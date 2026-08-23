"""SQLite schema for principal-owned MCP connection definitions."""

from __future__ import annotations

import sqlite3

from core.database import connect_sqlite_from_system_db
from core.database_migrations import SQLiteMigration, apply_sqlite_migrations

DB_NAME = "mcp"
MIGRATION_NAMESPACE = "mcp"
MCP_MIGRATIONS = (
    SQLiteMigration(
        version=1,
        name="principal_owned_connections",
        apply=lambda conn: _create_connection_tables(conn),
    ),
)


def ensure_mcp_schema(
    system_root: str | None = None, *, apply_migrations: bool = False
) -> None:
    """Create the current MCP connection schema."""
    conn = connect_sqlite_from_system_db(DB_NAME, system_root)
    try:
        if apply_migrations:
            apply_sqlite_migrations(
                conn,
                namespace=MIGRATION_NAMESPACE,
                migrations=MCP_MIGRATIONS,
            )
        else:
            _create_connection_tables(conn)
        conn.commit()
    finally:
        conn.close()


def connect_mcp(system_root: str | None = None) -> sqlite3.Connection:
    """Open the MCP database with named row access."""
    conn = connect_sqlite_from_system_db(DB_NAME, system_root)
    conn.row_factory = sqlite3.Row
    return conn


def _create_connection_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mcp_connection_slugs (
            connection_id TEXT PRIMARY KEY,
            owner_principal_id TEXT NOT NULL,
            slug TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(owner_principal_id, slug),
            CHECK (length(connection_id) > 0),
            CHECK (length(owner_principal_id) > 0),
            CHECK (length(slug) > 0)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mcp_connections (
            connection_id TEXT PRIMARY KEY,
            owner_principal_id TEXT NOT NULL,
            slug TEXT NOT NULL,
            display_name TEXT NOT NULL,
            url TEXT NOT NULL,
            transport TEXT NOT NULL,
            auth_mode TEXT NOT NULL,
            header_name TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            allowed_tools_json TEXT,
            config_version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(owner_principal_id, slug),
            CHECK (length(connection_id) > 0),
            CHECK (length(owner_principal_id) > 0),
            CHECK (length(slug) > 0),
            CHECK (length(display_name) > 0),
            CHECK (length(url) > 0),
            CHECK (transport IN ('streamable_http', 'sse')),
            CHECK (auth_mode IN ('none', 'bearer', 'header', 'oauth')),
            CHECK (enabled IN (0, 1)),
            CHECK (config_version > 0)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_mcp_connections_owner_enabled
        ON mcp_connections(owner_principal_id, enabled, display_name)
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO mcp_connection_slugs (
            connection_id, owner_principal_id, slug, created_at
        )
        SELECT connection_id, owner_principal_id, slug, created_at
        FROM mcp_connections
        """
    )
