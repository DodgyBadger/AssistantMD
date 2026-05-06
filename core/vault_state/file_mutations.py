"""Recorded vault file mutation operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from core.logger import UnifiedLogger
from core.runtime.execution_tasks import get_current_execution_task
from core.utils.hash import hash_file_bytes
from core.vault_state.identity import resolve_or_create_vault_identity
from core.vault_state.models import TaskFileMutation
from core.vault_state.pathing import normalize_vault_relative_path, resolve_vault_relative_path
from core.vault_state.service import VaultStateService
from core.vault_state.snapshots import compute_snapshot_expiration, ensure_task_file_snapshot


logger = UnifiedLogger(tag="vault-mutations")


class VaultMutationRejected(Exception):
    """Raised when a requested vault mutation is rejected before writing."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RecordedMutationResult:
    """Result of a recorded vault mutation."""

    vault_id: str
    vault_name: str
    path: str
    operation: str
    before_exists: bool
    before_hash: str | None
    after_exists: bool
    after_hash: str | None
    task_id: str | None
    event_sequence: int | None
    snapshot_ref: str | None


def write_vault_file(
    *,
    vault_path: str | Path,
    path: str,
    content: str,
    fail_if_exists: bool = True,
    markdown_only: bool = False,
) -> RecordedMutationResult:
    """Create or overwrite a vault file while recording task mutation metadata."""
    vault_root = Path(vault_path).resolve()
    relative_path = normalize_vault_relative_path(path)
    full_path = resolve_vault_relative_path(
        vault_path=vault_root,
        path=relative_path,
        markdown_only=markdown_only,
    )
    before_exists = full_path.exists()
    if before_exists and fail_if_exists:
        raise VaultMutationRejected(
            "file_exists",
            f"Cannot write to '{relative_path}' - file already exists.",
        )
    before_hash = hash_file_bytes(full_path, length=None) if before_exists else None

    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content, encoding="utf-8")

    after_exists = full_path.exists()
    after_hash = hash_file_bytes(full_path, length=None) if after_exists else None
    identity = resolve_or_create_vault_identity(vault_root)
    vault_name = vault_root.name
    task = get_current_execution_task()

    service = VaultStateService()
    refresh = service.refresh_vault(vault_root, vault_name=vault_name)
    event_sequence = refresh.latest_sequence
    result = RecordedMutationResult(
        vault_id=identity.vault_id,
        vault_name=vault_name,
        path=relative_path,
        operation="write",
        before_exists=before_exists,
        before_hash=before_hash,
        after_exists=after_exists,
        after_hash=after_hash,
        task_id=task.task_id if task is not None else None,
        event_sequence=event_sequence,
        snapshot_ref=None,
    )

    if task is None:
        logger.add_sink("validation").warning(
            "vault_state_mutation_untracked",
            data={
                "event": "vault_state_mutation_untracked",
                "vault_id": result.vault_id,
                "vault_name": result.vault_name,
                "path": result.path,
                "operation": result.operation,
                "reason": "missing_execution_task_context",
            },
        )
        return result

    created_at = datetime.now(UTC)
    expires_at = compute_snapshot_expiration(created_at)
    with service.SessionFactory() as session:
        snapshot = ensure_task_file_snapshot(
            session=session,
            task_id=task.task_id,
            vault_id=result.vault_id,
            vault_name=result.vault_name,
            vault_root=vault_root,
            relative_path=result.path,
            before_exists=result.before_exists,
            source_path=full_path,
            created_at=created_at,
            expires_at=expires_at,
        )
        result = RecordedMutationResult(
            vault_id=result.vault_id,
            vault_name=result.vault_name,
            path=result.path,
            operation=result.operation,
            before_exists=result.before_exists,
            before_hash=result.before_hash,
            after_exists=result.after_exists,
            after_hash=result.after_hash,
            task_id=result.task_id,
            event_sequence=result.event_sequence,
            snapshot_ref=snapshot.snapshot_ref,
        )
        session.add(
            TaskFileMutation(
                task_id=task.task_id,
                task_kind=task.kind,
                task_source=task.source,
                task_scope=task.scope,
                task_label=task.label,
                vault_id=result.vault_id,
                vault_name=result.vault_name,
                path=result.path,
                operation=result.operation,
                event_sequence=result.event_sequence,
                before_exists=result.before_exists,
                before_hash=result.before_hash,
                after_exists=result.after_exists,
                after_hash=result.after_hash,
                snapshot_ref=result.snapshot_ref,
                created_at=created_at,
                expires_at=expires_at,
            )
        )
        session.commit()

    logger.add_sink("validation").info(
        "task_file_mutation_recorded",
        data={
            "event": "task_file_mutation_recorded",
            "task_id": task.task_id,
            "task_kind": task.kind,
            "task_source": task.source,
            "task_scope": task.scope,
            "task_label": task.label,
            "vault_id": result.vault_id,
            "vault_name": result.vault_name,
            "path": result.path,
            "operation": result.operation,
            "before_exists": result.before_exists,
            "after_exists": result.after_exists,
            "before_hash": result.before_hash,
            "after_hash": result.after_hash,
            "event_sequence": result.event_sequence,
            "expires_at": expires_at.isoformat(),
            "snapshot_ref": result.snapshot_ref,
        },
    )
    return result
