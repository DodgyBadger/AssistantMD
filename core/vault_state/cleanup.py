"""Manual cleanup for expired vault-state safety artifacts."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from core.database import get_system_database_path
from core.logger import UnifiedLogger
from core.vault_state.models import FileSnapshot, SnapshotSet, TaskFileMutation
from core.vault_state.service import VaultStateService


logger = UnifiedLogger(tag="vault-state-cleanup")


@dataclass(frozen=True)
class VaultStateCleanupResult:
    """Summary of one vault-state cleanup run."""

    expired_mutation_rows_deleted: int
    expired_snapshot_rows_deleted: int
    snapshot_files_deleted: int
    snapshot_dirs_deleted: int


def cleanup_expired_vault_state(now: datetime | None = None) -> VaultStateCleanupResult:
    """Delete expired task mutation rows and snapshot artifacts."""
    cleanup_time = now or datetime.now(UTC)
    snapshot_base = _snapshot_base_root().resolve()
    service = VaultStateService()
    expired_mutation_rows_deleted = 0
    expired_snapshot_rows_deleted = 0
    snapshot_files_deleted = 0
    snapshot_dirs_deleted = 0

    with service.SessionFactory() as session:
        expired_mutations = [
            row
            for row in session.query(TaskFileMutation).all()
            if _is_expired(row.expires_at, cleanup_time)
        ]
        for row in expired_mutations:
            session.delete(row)
        expired_mutation_rows_deleted = len(expired_mutations)

        expired_snapshots = [
            row
            for row in session.query(SnapshotSet).all()
            if _is_expired(row.expires_at, cleanup_time)
        ]
        for row in expired_snapshots:
            files_deleted, dirs_deleted = _delete_snapshot_root(
                snapshot_root=Path(row.snapshot_root),
                snapshot_base=snapshot_base,
            )
            snapshot_files_deleted += files_deleted
            snapshot_dirs_deleted += dirs_deleted
            for file_snapshot in (
                session.query(FileSnapshot)
                .filter(FileSnapshot.snapshot_set_id == row.id)
                .all()
            ):
                session.delete(file_snapshot)
            session.delete(row)
        expired_snapshot_rows_deleted = len(expired_snapshots)
        session.commit()

    result = VaultStateCleanupResult(
        expired_mutation_rows_deleted=expired_mutation_rows_deleted,
        expired_snapshot_rows_deleted=expired_snapshot_rows_deleted,
        snapshot_files_deleted=snapshot_files_deleted,
        snapshot_dirs_deleted=snapshot_dirs_deleted,
    )
    logger.add_sink("validation").info(
        "vault_state_cleanup_completed",
        data={
            "event": "vault_state_cleanup_completed",
            "expired_mutation_rows_deleted": result.expired_mutation_rows_deleted,
            "expired_snapshot_rows_deleted": result.expired_snapshot_rows_deleted,
            "snapshot_files_deleted": result.snapshot_files_deleted,
            "snapshot_dirs_deleted": result.snapshot_dirs_deleted,
            "now": cleanup_time.isoformat(),
        },
    )
    return result


def _is_expired(value: object, now: datetime) -> bool:
    if value is None:
        return False
    expires_at = value
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            expires_at = datetime.fromisoformat(normalized)
        except ValueError:
            logger.warning(
                "Ignoring malformed vault-state expiration timestamp",
                data={"expires_at": value},
            )
            return False
    if not isinstance(expires_at, datetime):
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    comparison_now = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    return expires_at <= comparison_now


def _delete_snapshot_root(*, snapshot_root: Path, snapshot_base: Path) -> tuple[int, int]:
    """Delete one snapshot root only when it lives under the managed snapshot base."""
    resolved_root = snapshot_root.resolve()
    try:
        resolved_root.relative_to(snapshot_base)
    except ValueError:
        logger.warning(
            "Refusing to delete snapshot root outside managed base",
            data={
                "snapshot_root": str(resolved_root),
                "snapshot_base": str(snapshot_base),
            },
        )
        return 0, 0
    if resolved_root == snapshot_base or not resolved_root.exists():
        return 0, 0
    if not resolved_root.is_dir():
        resolved_root.unlink(missing_ok=True)
        return 1, 0

    file_count = sum(1 for item in resolved_root.rglob("*") if item.is_file())
    dir_count = sum(1 for item in resolved_root.rglob("*") if item.is_dir()) + 1
    shutil.rmtree(resolved_root)
    return file_count, dir_count


def _snapshot_base_root() -> Path:
    system_root = Path(get_system_database_path("vault_state")).parent
    return system_root / "task_snapshots"
