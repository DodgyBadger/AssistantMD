"""SQLite schema for principal-owned encrypted secrets."""

from __future__ import annotations

import sqlite3

from core.database import connect_sqlite_from_system_db

DB_NAME = "secrets"


def ensure_secrets_schema(system_root: str | None = None) -> None:
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
        conn.commit()
    finally:
        conn.close()


def connect_secrets(system_root: str | None = None) -> sqlite3.Connection:
    """Open the declared secrets database with row access by column name."""
    conn = connect_sqlite_from_system_db(DB_NAME, system_root)
    conn.row_factory = sqlite3.Row
    return conn
