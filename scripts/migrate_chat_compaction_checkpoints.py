#!/usr/bin/env python3
"""Apply chat compaction checkpoint schema migration to a live system DB."""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.chat.schema import ensure_chat_sessions_schema  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply chat compaction checkpoint migrations to chat_sessions.db."
    )
    parser.add_argument(
        "--system-root",
        default=str(REPO_ROOT / "system"),
        help="Path to the AssistantMD system directory. Defaults to ./system.",
    )
    parser.add_argument(
        "--skip-backup",
        action="store_true",
        help="Do not create a timestamped chat_sessions.db backup before migrating.",
    )
    parser.add_argument(
        "--status-only",
        action="store_true",
        help="Only report migration status; do not modify the database.",
    )
    args = parser.parse_args()

    system_root = Path(args.system_root).expanduser().resolve()
    db_path = system_root / "chat_sessions.db"
    if not db_path.exists():
        raise SystemExit(f"chat_sessions.db not found: {db_path}")

    before = _migration_status(db_path)
    if args.status_only:
        _print_status(db_path, before)
        return 0

    backup_path = None
    if not args.skip_backup:
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        backup_path = system_root / f"chat_sessions.db.backup-{timestamp}"
        shutil.copy2(db_path, backup_path)

    ensure_chat_sessions_schema(str(system_root))

    after = _migration_status(db_path)
    if not after["checkpoint_table"]:
        raise SystemExit("Migration failed: chat_compaction_checkpoints table was not created.")
    if 1 not in after["chat_session_versions"]:
        raise SystemExit("Migration failed: chat_sessions migration version 1 was not recorded.")

    print(f"Migrated chat sessions database: {db_path}")
    if backup_path is not None:
        print(f"Backup created at: {backup_path}")
    print(f"checkpoint_table: {after['checkpoint_table']}")
    print(f"checkpoint_indexes: {', '.join(after['checkpoint_indexes']) or '(none)'}")
    print(f"chat_sessions migrations: {after['chat_session_versions']}")
    if before == after:
        print("No schema changes were needed; migration was already applied.")
    return 0


def _migration_status(db_path: Path) -> dict[str, object]:
    conn = sqlite3.connect(db_path)
    try:
        checkpoint_table = _table_exists(conn, "chat_compaction_checkpoints")
        checkpoint_indexes = [
            str(row[0])
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'index'
                  AND tbl_name = 'chat_compaction_checkpoints'
                ORDER BY name
                """
            ).fetchall()
        ]
        chat_session_versions: list[int] = []
        if _table_exists(conn, "schema_migrations"):
            chat_session_versions = [
                int(row[0])
                for row in conn.execute(
                    """
                    SELECT version
                    FROM schema_migrations
                    WHERE namespace = 'chat_sessions'
                    ORDER BY version
                    """
                ).fetchall()
            ]
    finally:
        conn.close()
    return {
        "checkpoint_table": checkpoint_table,
        "checkpoint_indexes": checkpoint_indexes,
        "chat_session_versions": chat_session_versions,
    }


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        LIMIT 1
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def _print_status(db_path: Path, status: dict[str, object]) -> None:
    print(f"Database: {db_path}")
    print(f"checkpoint_table: {status['checkpoint_table']}")
    print(f"checkpoint_indexes: {', '.join(status['checkpoint_indexes']) or '(none)'}")
    print(f"chat_sessions migrations: {status['chat_session_versions']}")


if __name__ == "__main__":
    raise SystemExit(main())
