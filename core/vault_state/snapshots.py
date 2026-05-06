"""Task snapshot capture for vault mutations."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from core.database import get_system_database_path
from core.logger import UnifiedLogger
from core.settings import get_task_snapshot_retention_days
from core.vault_state.models import TaskFileMutation, TaskSnapshot


logger = UnifiedLogger(tag="vault-snapshots")


@dataclass(frozen=True)
class SnapshotCaptureResult:
    """Result of ensuring a task snapshot for one path."""

    snapshot_ref: str | None
    created_snapshot: bool
    recorded_path: bool


def ensure_task_file_snapshot(
    *,
    session,
    task_id: str,
    vault_id: str,
    vault_name: str,
    vault_root: Path,
    relative_path: str,
    before_exists: bool,
    source_path: Path,
    created_at: datetime,
    expires_at: datetime | None,
) -> SnapshotCaptureResult:
    """Capture the original file state once per task/path before mutation."""
    existing = (
        session.query(TaskFileMutation)
        .filter(
            TaskFileMutation.task_id == task_id,
            TaskFileMutation.vault_id == vault_id,
            TaskFileMutation.path == relative_path,
        )
        .order_by(TaskFileMutation.id.asc())
        .first()
    )
    if existing is not None:
        return SnapshotCaptureResult(
            snapshot_ref=existing.snapshot_ref,
            created_snapshot=False,
            recorded_path=False,
        )

    snapshot_root = _snapshot_root(task_id)
    snapshot = session.get(TaskSnapshot, (task_id, vault_id))
    created_snapshot = False
    if snapshot is None:
        snapshot_root.mkdir(parents=True, exist_ok=True)
        snapshot = TaskSnapshot(
            task_id=task_id,
            vault_id=vault_id,
            vault_name=vault_name,
            snapshot_root=str(snapshot_root),
            status="active",
            created_at=created_at,
            expires_at=expires_at,
            rolled_back_at=None,
        )
        session.add(snapshot)
        created_snapshot = True
        logger.add_sink("validation").info(
            "task_snapshot_created",
            data={
                "event": "task_snapshot_created",
                "task_id": task_id,
                "vault_id": vault_id,
                "vault_name": vault_name,
                "snapshot_root": str(snapshot_root),
                "expires_at": expires_at.isoformat() if expires_at else None,
            },
        )

    snapshot_ref = None
    if before_exists:
        snapshot_ref = _snapshot_ref(relative_path)
        target_path = snapshot_root / snapshot_ref
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)

    logger.add_sink("validation").info(
        "task_file_snapshot_recorded",
        data={
            "event": "task_file_snapshot_recorded",
            "task_id": task_id,
            "vault_id": vault_id,
            "vault_name": vault_name,
            "path": relative_path,
            "before_exists": before_exists,
            "snapshot_ref": snapshot_ref,
        },
    )
    return SnapshotCaptureResult(
        snapshot_ref=snapshot_ref,
        created_snapshot=created_snapshot,
        recorded_path=True,
    )


def compute_snapshot_expiration(created_at: datetime) -> datetime | None:
    """Return snapshot expiration using task retention settings."""
    retention_days = get_task_snapshot_retention_days()
    if retention_days <= 0:
        return created_at
    return created_at + timedelta(days=retention_days)


def _snapshot_root(task_id: str) -> Path:
    system_root = Path(get_system_database_path("vault_state")).parent
    return system_root / "task_snapshots" / task_id


def _snapshot_ref(relative_path: str) -> str:
    return str(Path("files") / relative_path)
