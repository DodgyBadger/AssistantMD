"""Integration scenario for registered system database migrations."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from core.chat import ChatStore
from core.system_migrations import get_system_migration_status, run_system_migrations
from validation.core.base_scenario import BaseScenario


class SystemDatabaseMigrationsScenario(BaseScenario):
    """Validate release migration status, execution, and backup creation."""

    async def test_scenario(self):
        system_root = self.artifacts_dir / "system"
        system_root.mkdir(parents=True, exist_ok=True)
        chat_db = system_root / "chat_sessions.db"
        self._create_legacy_chat_sessions_db(chat_db)

        ChatStore(str(system_root))
        before = get_system_migration_status(system_root)
        self.soft_assert_equal(
            before.pending_count,
            5,
            "Store initialization should not apply registered release migrations",
        )

        after = run_system_migrations(system_root, backup=True)
        self.soft_assert_equal(after.pending_count, 0, "Registered migrations should be applied")

        target_by_db = {target.db_name: target for target in after.targets}
        chat_target = target_by_db["chat_sessions"]
        summary_target = target_by_db["session_summaries"]
        goal_target = target_by_db["goal_ops"]
        self.soft_assert(chat_target.backup_path is not None, "Existing chat DB should be backed up")
        self.soft_assert(summary_target.backup_path is None, "New summary DB should not create an empty backup")
        self.soft_assert(goal_target.backup_path is None, "New goal_ops DB should not create an empty backup")
        if chat_target.backup_path:
            self.soft_assert(Path(chat_target.backup_path).exists(), "Chat DB backup should exist")

        with sqlite3.connect(chat_db) as conn:
            self.soft_assert(
                self._table_exists(conn, "chat_compaction_checkpoints"),
                "Chat checkpoint table should exist after migration",
            )
            self.soft_assert_equal(
                self._migration_versions(conn, "chat_sessions"),
                [1],
                "Chat migration version should be recorded",
            )

        with sqlite3.connect(system_root / "session_summaries.db") as conn:
            self.soft_assert_equal(
                self._migration_versions(conn, "session_summaries"),
                [1, 2, 3],
                "Session summary migration versions should be recorded",
            )

        with sqlite3.connect(system_root / "goal_ops.db") as conn:
            self.soft_assert(
                self._table_exists(conn, "goals"),
                "goal_ops goals table should exist after migration",
            )
            self.soft_assert_equal(
                self._migration_versions(conn, "goal_ops"),
                [1],
                "goal_ops migration version should be recorded",
            )

        second = run_system_migrations(system_root, backup=True)
        self.soft_assert_equal(second.pending_count, 0, "Second run should remain fully applied")
        self.soft_assert(
            all(target.backup_path is None for target in second.targets),
            "Second run should not create backups when no migrations are pending",
        )
        self.teardown_scenario()

    @staticmethod
    def _create_legacy_chat_sessions_db(db_path: Path) -> None:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE chat_sessions (
                    session_id TEXT NOT NULL,
                    vault_name TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_activity_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    title TEXT,
                    metadata_json TEXT,
                    PRIMARY KEY (session_id, vault_name)
                )
                """
            )

    @staticmethod
    def _migration_versions(conn: sqlite3.Connection, namespace: str) -> list[int]:
        return [
            int(row[0])
            for row in conn.execute(
                """
                SELECT version
                FROM schema_migrations
                WHERE namespace = ?
                ORDER BY version
                """,
                (namespace,),
            ).fetchall()
        ]

    @staticmethod
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
