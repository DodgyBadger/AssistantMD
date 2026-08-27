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
    SQLiteMigration(
        version=2,
        name="oauth_client_configuration",
        apply=lambda conn: _add_oauth_client_columns(conn),
    ),
    SQLiteMigration(
        version=3,
        name="durable_connection_mutations",
        apply=lambda conn: _add_connection_mutation_lifecycle(conn),
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
            if not _table_exists(conn, "mcp_connections"):
                _create_connection_tables(conn)
            _assert_current_schema(conn)
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
            oauth_client_id TEXT,
            oauth_scopes_json TEXT,
            config_version INTEGER NOT NULL DEFAULT 1,
            lifecycle_state TEXT NOT NULL DEFAULT 'active',
            oauth_fence_token TEXT NOT NULL
                DEFAULT (lower(hex(randomblob(16)))),
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
            CHECK (config_version > 0),
            CHECK (lifecycle_state IN ('active', 'pending', 'deleting')),
            CHECK (length(oauth_fence_token) = 32)
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
        CREATE INDEX IF NOT EXISTS idx_mcp_connections_owner_lifecycle_enabled
        ON mcp_connections(
            owner_principal_id, lifecycle_state, enabled, display_name
        )
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
    _create_mutation_table(conn)


def _add_oauth_client_columns(conn: sqlite3.Connection) -> None:
    columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(mcp_connections)").fetchall()
    }
    if "oauth_client_id" not in columns:
        conn.execute("ALTER TABLE mcp_connections ADD COLUMN oauth_client_id TEXT")
    if "oauth_scopes_json" not in columns:
        conn.execute("ALTER TABLE mcp_connections ADD COLUMN oauth_scopes_json TEXT")


def _add_connection_mutation_lifecycle(conn: sqlite3.Connection) -> None:
    columns = _connection_columns(conn)
    if "lifecycle_state" not in columns:
        conn.execute(
            """
            ALTER TABLE mcp_connections
            ADD COLUMN lifecycle_state TEXT NOT NULL DEFAULT 'active'
            CHECK (lifecycle_state IN ('active', 'pending', 'deleting'))
            """
        )
    if "oauth_fence_token" not in columns:
        conn.execute("ALTER TABLE mcp_connections ADD COLUMN oauth_fence_token TEXT")
        conn.execute(
            """
            UPDATE mcp_connections
            SET oauth_fence_token = lower(hex(randomblob(16)))
            WHERE oauth_fence_token IS NULL
            """
        )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_mcp_connections_owner_lifecycle_enabled
        ON mcp_connections(
            owner_principal_id, lifecycle_state, enabled, display_name
        )
        """
    )
    _create_mutation_table(conn)


def _create_mutation_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mcp_connection_mutations (
            operation_id TEXT PRIMARY KEY,
            owner_principal_id TEXT NOT NULL,
            connection_id TEXT NOT NULL,
            mutation_kind TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'staging',
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_error_class TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(owner_principal_id, connection_id),
            CHECK (length(operation_id) > 0),
            CHECK (length(owner_principal_id) > 0),
            CHECK (length(connection_id) > 0),
            CHECK (mutation_kind IN (
                'create', 'update', 'set_credential',
                'set_oauth_client_secret', 'clear_credential',
                'disconnect_oauth', 'delete'
            )),
            CHECK (state IN (
                'staging', 'intent', 'secrets_applied', 'finalized'
            )),
            CHECK (attempt_count >= 0)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_mcp_connection_mutations_state_updated
        ON mcp_connection_mutations(state, updated_at)
        """
    )


def _assert_current_schema(conn: sqlite3.Connection) -> None:
    required = {
        "oauth_client_id",
        "oauth_scopes_json",
        "lifecycle_state",
        "oauth_fence_token",
    }
    missing = sorted(required - _connection_columns(conn))
    if missing:
        raise RuntimeError(
            "MCP schema is not current; run managed system migrations before "
            f"constructing MCP services (missing: {', '.join(missing)})."
        )
    if not conn.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type = 'table' AND name = 'mcp_connection_mutations'
        """
    ).fetchone():
        raise RuntimeError(
            "MCP schema is not current; run managed system migrations before "
            "constructing MCP services (missing mutation journal)."
        )


def _connection_columns(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(mcp_connections)").fetchall()
    }


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return (
        conn.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = ?
            """,
            (table_name,),
        ).fetchone()
        is not None
    )
