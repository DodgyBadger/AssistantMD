"""SQLite schema for principal-owned encrypted secrets."""

from __future__ import annotations

import sqlite3

from core.database import connect_sqlite_from_system_db
from core.database_migrations import SQLiteMigration, apply_sqlite_migrations

DB_NAME = "secrets"
MIGRATION_NAMESPACE = "secrets"
SECRETS_MIGRATIONS = (
    SQLiteMigration(
        version=1,
        name="principal_owned_encrypted_secrets",
        apply=lambda _conn: None,
    ),
)


def ensure_secrets_schema(
    system_root: str | None = None, *, apply_migrations: bool = False
) -> None:
    """Create the current encrypted-secrets schema."""
    conn = connect_sqlite_from_system_db(DB_NAME, system_root)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS encrypted_secrets (
                owner_principal_id TEXT NOT NULL,
                namespace TEXT NOT NULL,
                name TEXT NOT NULL,
                envelope_version INTEGER NOT NULL,
                key_version INTEGER NOT NULL,
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (owner_principal_id, namespace, name),
                CHECK (length(owner_principal_id) > 0),
                CHECK (length(namespace) > 0),
                CHECK (length(name) > 0),
                CHECK (envelope_version > 0),
                CHECK (key_version > 0),
                CHECK (length(nonce) = 12)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_encrypted_secrets_owner_namespace
            ON encrypted_secrets(owner_principal_id, namespace, name)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS secrets_bootstrap_migrations (
                migration_name TEXT PRIMARY KEY,
                phase TEXT NOT NULL,
                source_fingerprint TEXT,
                imported_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CHECK (phase IN ('imported', 'complete')),
                CHECK (imported_count >= 0)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS secrets_bootstrap_import_items (
                migration_name TEXT NOT NULL,
                owner_principal_id TEXT NOT NULL,
                namespace TEXT NOT NULL,
                name TEXT NOT NULL,
                PRIMARY KEY (
                    migration_name, owner_principal_id, namespace, name
                ),
                FOREIGN KEY (migration_name)
                    REFERENCES secrets_bootstrap_migrations(migration_name)
                    ON DELETE CASCADE
            )
            """
        )
        if apply_migrations:
            apply_sqlite_migrations(
                conn,
                namespace=MIGRATION_NAMESPACE,
                migrations=SECRETS_MIGRATIONS,
            )
        conn.commit()
    finally:
        conn.close()


def connect_secrets(system_root: str | None = None) -> sqlite3.Connection:
    """Open the declared secrets database with row access by column name."""
    conn = connect_sqlite_from_system_db(DB_NAME, system_root)
    conn.row_factory = sqlite3.Row
    return conn
