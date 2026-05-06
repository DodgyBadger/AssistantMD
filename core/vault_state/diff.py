"""Vault file diff helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import difflib
from pathlib import Path
from typing import Any

from sqlalchemy import select

from core.settings import get_task_snapshot_retention_days
from core.utils.hash import hash_file_bytes, hash_file_content
from core.vault_state.models import TaskFileMutation, TaskSnapshot
from core.vault_state.pathing import normalize_vault_relative_path, resolve_vault_relative_path
from core.vault_state.service import VaultStateService


@dataclass(frozen=True)
class FileDiffResult:
    """Result of diffing the current file against the latest retained snapshot."""

    available: bool
    status: str
    path: str
    reason: str = ""
    message: str = ""
    has_changes: bool = False
    text: str = ""
    format: str = "unified"
    baseline: dict[str, Any] = field(default_factory=dict)
    current: dict[str, Any] = field(default_factory=dict)


def diff_file_against_previous(
    *,
    vault_path: str | Path,
    path: str,
) -> FileDiffResult:
    """Return a unified diff from the latest retained prior snapshot to current."""
    vault_root = Path(vault_path).resolve()
    vault_name = vault_root.name
    relative_path = normalize_vault_relative_path(path)
    current_path = resolve_vault_relative_path(vault_path=vault_root, path=relative_path)
    service = VaultStateService()

    with service.SessionFactory() as session:
        row = session.scalars(
            select(TaskFileMutation)
            .where(
                TaskFileMutation.vault_name == vault_name,
                TaskFileMutation.path == relative_path,
                TaskFileMutation.before_exists.is_(True),
                TaskFileMutation.snapshot_ref.is_not(None),
            )
            .order_by(TaskFileMutation.created_at.desc(), TaskFileMutation.id.desc())
        ).first()
        if row is None:
            return _unavailable(relative_path, "previous_snapshot_unavailable")

        snapshot = session.get(TaskSnapshot, (row.task_id, row.vault_id))
        if snapshot is None or not row.snapshot_ref:
            return _unavailable(relative_path, "previous_snapshot_unavailable")

        snapshot_path = (Path(snapshot.snapshot_root) / row.snapshot_ref).resolve()
        if not snapshot_path.exists() or not snapshot_path.is_file():
            return _unavailable(relative_path, "previous_snapshot_unavailable")

        baseline_text = snapshot_path.read_text(encoding="utf-8")
        baseline_hash = hash_file_content(baseline_text, length=None)
        baseline = {
            "kind": "previous",
            "task_id": row.task_id,
            "created_at": _isoformat(row.created_at),
            "content_hash": baseline_hash,
            "snapshot_ref": row.snapshot_ref,
        }

    current_exists = current_path.exists()
    current_text = current_path.read_text(encoding="utf-8") if current_exists else ""
    current_hash = hash_file_bytes(current_path, length=None) if current_exists else None
    current = {
        "kind": "current",
        "exists": current_exists,
        "content_hash": current_hash,
    }
    diff_text = "".join(
        difflib.unified_diff(
            baseline_text.splitlines(keepends=True),
            current_text.splitlines(keepends=True),
            fromfile=f"{relative_path} (previous)",
            tofile=f"{relative_path} (current)",
        )
    )
    return FileDiffResult(
        available=True,
        status="completed",
        path=relative_path,
        has_changes=bool(diff_text),
        text=diff_text,
        baseline=baseline,
        current=current,
    )


def _unavailable(path: str, reason: str) -> FileDiffResult:
    retention_days = get_task_snapshot_retention_days()
    return FileDiffResult(
        available=False,
        status="unavailable",
        path=path,
        reason=reason,
        message=(
            f"No retained previous snapshot is available for {path}. "
            f"Increase task_snapshot_retention_days above {retention_days} to retain snapshots longer."
        ),
    )


def _isoformat(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None
