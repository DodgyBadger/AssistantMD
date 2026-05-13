"""Task-scoped snapshot set and file snapshot capture."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from core.database import get_system_database_path
from core.logger import UnifiedLogger
from core.settings import get_task_snapshot_retention_days
from core.vault_state.models import FileSnapshot, SnapshotSet


logger = UnifiedLogger(tag="vault-snapshots")


@dataclass(frozen=True)
class SnapshotCaptureResult:
    """Result of ensuring a task snapshot for one path."""

    snapshot_set_id: int | None
    file_snapshot_id: int | None
    snapshot_ref: str | None
    created_snapshot: bool
    recorded_path: bool


def ensure_task_file_snapshot(
    *,
    session,
    task_id: str,
    task_kind: str | None = None,
    task_source: str | None = None,
    task_scope: str | None = None,
    task_label: str | None = None,
    vault_id: str,
    vault_name: str,
    vault_root: Path,
    relative_path: str,
    before_exists: bool,
    source_path: Path,
    purpose: str = "rollback",
    source: str = "task_mutation_before",
    scope_kind: str | None = None,
    scope_id: str | None = None,
    created_at: datetime,
    expires_at: datetime | None,
) -> SnapshotCaptureResult:
    """Capture one file state once for a task/vault/path/source."""
    existing = (
        session.query(FileSnapshot)
        .filter(
            FileSnapshot.task_id == task_id,
            FileSnapshot.vault_id == vault_id,
            FileSnapshot.path == relative_path,
            FileSnapshot.source == source,
        )
        .order_by(FileSnapshot.id.asc())
        .first()
    )
    if existing is not None:
        return SnapshotCaptureResult(
            snapshot_set_id=existing.snapshot_set_id,
            file_snapshot_id=existing.id,
            snapshot_ref=existing.snapshot_ref,
            created_snapshot=False,
            recorded_path=False,
        )

    snapshot = (
        session.query(SnapshotSet)
        .filter(
            SnapshotSet.task_id == task_id,
            SnapshotSet.vault_id == vault_id,
            SnapshotSet.purpose == purpose,
        )
        .order_by(SnapshotSet.id.asc())
        .first()
    )
    created_snapshot = False
    if snapshot is None:
        snapshot = SnapshotSet(
            task_id=task_id,
            task_kind=task_kind,
            task_source=task_source,
            task_scope=task_scope,
            task_label=task_label,
            vault_id=vault_id,
            vault_name=vault_name,
            purpose=purpose,
            scope_kind=scope_kind,
            scope_id=scope_id,
            snapshot_root="",
            status="active",
            created_at=created_at,
            expires_at=expires_at,
            rolled_back_at=None,
        )
        session.add(snapshot)
        session.flush()
        snapshot_root = _snapshot_root(snapshot.id)
        snapshot_root.mkdir(parents=True, exist_ok=True)
        snapshot.snapshot_root = str(snapshot_root)
        created_snapshot = True
        logger.add_sink("validation").info(
            "snapshot_set_created",
            data={
                "event": "snapshot_set_created",
                "snapshot_set_id": snapshot.id,
                "task_id": task_id,
                "vault_id": vault_id,
                "vault_name": vault_name,
                "purpose": purpose,
                "snapshot_root": str(snapshot_root),
                "expires_at": expires_at.isoformat() if expires_at else None,
            },
        )
    else:
        snapshot_root = Path(snapshot.snapshot_root)

    snapshot_ref = None
    content_hash = None
    if before_exists:
        snapshot_ref = _snapshot_ref(source, relative_path)
        content_hash = _hash_existing_file(source_path)
        target_path = snapshot_root / snapshot_ref
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)

    file_snapshot = FileSnapshot(
        snapshot_set_id=snapshot.id,
        task_id=task_id,
        vault_id=vault_id,
        vault_name=vault_name,
        path=relative_path,
        source=source,
        exists=before_exists,
        content_hash=content_hash,
        snapshot_ref=snapshot_ref,
        created_at=created_at,
        expires_at=expires_at,
    )
    session.add(file_snapshot)
    session.flush()

    logger.add_sink("validation").info(
        "task_file_snapshot_recorded",
        data={
            "event": "task_file_snapshot_recorded",
            "snapshot_set_id": snapshot.id,
            "file_snapshot_id": file_snapshot.id,
            "task_id": task_id,
            "vault_id": vault_id,
            "vault_name": vault_name,
            "path": relative_path,
            "before_exists": before_exists,
            "source": source,
            "snapshot_ref": snapshot_ref,
        },
    )
    return SnapshotCaptureResult(
        snapshot_set_id=snapshot.id,
        file_snapshot_id=file_snapshot.id,
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


def _snapshot_root(snapshot_set_id: int) -> Path:
    system_root = Path(get_system_database_path("vault_state")).parent
    return system_root / "vault_snapshots" / str(snapshot_set_id)


def _snapshot_ref(source: str, relative_path: str) -> str:
    return str(Path(source) / "files" / relative_path)


def _hash_existing_file(path: Path) -> str:
    from core.utils.hash import hash_file_bytes

    return hash_file_bytes(path, length=None)
