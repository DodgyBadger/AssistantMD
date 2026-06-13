"""Release-oriented system database migration orchestration."""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from core.chat.schema import (
    CHAT_SESSION_MIGRATIONS,
    DB_NAME as CHAT_SESSIONS_DB_NAME,
    MIGRATION_NAMESPACE as CHAT_SESSIONS_MIGRATION_NAMESPACE,
    ensure_chat_sessions_schema,
)
from core.database import get_system_database_path
from core.database_migrations import SQLiteMigration
from core.goals.schema import (
    DB_NAME as GOAL_OPS_DB_NAME,
    GOAL_OPS_MIGRATIONS,
    MIGRATION_NAMESPACE as GOAL_OPS_MIGRATION_NAMESPACE,
    ensure_goal_ops_schema,
)
from core.logger import UnifiedLogger
from core.memory.schema import (
    DB_NAME as SESSION_SUMMARIES_DB_NAME,
    MIGRATION_NAMESPACE as SESSION_SUMMARIES_MIGRATION_NAMESPACE,
    SESSION_SUMMARY_MIGRATIONS,
    ensure_session_summary_schema,
)
from core.runtime.paths import get_system_root


logger = UnifiedLogger(tag="system_migrations")


@dataclass(frozen=True)
class SystemMigrationTarget:
    """One managed system database migration target."""

    db_name: str
    namespace: str
    migrations: Sequence[SQLiteMigration]
    ensure_schema: Callable[[str | None], None]


@dataclass(frozen=True)
class SystemMigrationTargetStatus:
    """Status for one managed system database migration target."""

    db_name: str
    namespace: str
    db_path: str
    exists: bool
    applied_versions: tuple[int, ...]
    pending_versions: tuple[int, ...]
    backup_path: str | None = None


@dataclass(frozen=True)
class SystemMigrationStatus:
    """Aggregate status for all managed system database migration targets."""

    system_root: str
    targets: tuple[SystemMigrationTargetStatus, ...]

    @property
    def pending_count(self) -> int:
        return sum(len(target.pending_versions) for target in self.targets)


MIGRATION_TARGETS: tuple[SystemMigrationTarget, ...] = (
    SystemMigrationTarget(
        db_name=CHAT_SESSIONS_DB_NAME,
        namespace=CHAT_SESSIONS_MIGRATION_NAMESPACE,
        migrations=CHAT_SESSION_MIGRATIONS,
        ensure_schema=lambda system_root: ensure_chat_sessions_schema(
            system_root,
            apply_migrations=True,
        ),
    ),
    SystemMigrationTarget(
        db_name=SESSION_SUMMARIES_DB_NAME,
        namespace=SESSION_SUMMARIES_MIGRATION_NAMESPACE,
        migrations=SESSION_SUMMARY_MIGRATIONS,
        ensure_schema=lambda system_root: ensure_session_summary_schema(
            system_root,
            apply_migrations=True,
        ),
    ),
    SystemMigrationTarget(
        db_name=GOAL_OPS_DB_NAME,
        namespace=GOAL_OPS_MIGRATION_NAMESPACE,
        migrations=GOAL_OPS_MIGRATIONS,
        ensure_schema=lambda system_root: ensure_goal_ops_schema(
            system_root,
            apply_migrations=True,
        ),
    ),
)


def get_system_migration_status(system_root: str | Path | None = None) -> SystemMigrationStatus:
    """Return pending system database migrations without mutating databases."""
    root = _resolve_system_root(system_root)
    targets = tuple(_target_status(target, root) for target in MIGRATION_TARGETS)
    return SystemMigrationStatus(system_root=str(root), targets=targets)


def run_system_migrations(
    system_root: str | Path | None = None,
    *,
    backup: bool = True,
) -> SystemMigrationStatus:
    """Apply all registered system database migrations and return final status."""
    root = _resolve_system_root(system_root)
    before = get_system_migration_status(root)
    backup_paths = _backup_pending_databases(before) if backup else {}

    for target in MIGRATION_TARGETS:
        target.ensure_schema(str(root))

    after = get_system_migration_status(root)
    targets = tuple(
        SystemMigrationTargetStatus(
            db_name=target_status.db_name,
            namespace=target_status.namespace,
            db_path=target_status.db_path,
            exists=target_status.exists,
            applied_versions=target_status.applied_versions,
            pending_versions=target_status.pending_versions,
            backup_path=backup_paths.get(target_status.db_name),
        )
        for target_status in after.targets
    )
    result = SystemMigrationStatus(system_root=after.system_root, targets=targets)

    logger.info(
        "System database migrations completed",
        data={
            "system_root": result.system_root,
            "pending_before": before.pending_count,
            "pending_after": result.pending_count,
            "backups_created": len(backup_paths),
        },
    )
    return result


def _resolve_system_root(system_root: str | Path | None) -> Path:
    if system_root is None:
        return get_system_root().resolve()
    return Path(system_root).expanduser().resolve()


def _target_status(target: SystemMigrationTarget, system_root: Path) -> SystemMigrationTargetStatus:
    db_path = Path(get_system_database_path(target.db_name, str(system_root)))
    applied_versions = _applied_versions(db_path, namespace=target.namespace) if db_path.exists() else tuple()
    declared_versions = tuple(migration.version for migration in sorted(target.migrations, key=lambda item: item.version))
    applied_set = set(applied_versions)
    pending_versions = tuple(version for version in declared_versions if version not in applied_set)
    return SystemMigrationTargetStatus(
        db_name=target.db_name,
        namespace=target.namespace,
        db_path=str(db_path),
        exists=db_path.exists(),
        applied_versions=applied_versions,
        pending_versions=pending_versions,
    )


def _applied_versions(db_path: Path, *, namespace: str) -> tuple[int, ...]:
    conn = sqlite3.connect(db_path)
    try:
        if not _table_exists(conn, "schema_migrations"):
            return tuple()
        rows = conn.execute(
            """
            SELECT version
            FROM schema_migrations
            WHERE namespace = ?
            ORDER BY version
            """,
            (namespace,),
        ).fetchall()
    finally:
        conn.close()
    return tuple(int(row[0]) for row in rows)


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


def _backup_pending_databases(status: SystemMigrationStatus) -> dict[str, str]:
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    backups: dict[str, str] = {}
    for target in status.targets:
        if not target.exists or not target.pending_versions:
            continue
        source = Path(target.db_path)
        backup_path = source.with_name(f"{source.name}.backup-{timestamp}")
        shutil.copy2(source, backup_path)
        backups[target.db_name] = str(backup_path)
    return backups
