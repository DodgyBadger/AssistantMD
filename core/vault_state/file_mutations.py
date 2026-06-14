"""Recorded vault file mutation operations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import os
from pathlib import Path
from typing import Any

from core.logger import UnifiedLogger
from core.runtime.execution_tasks import get_current_execution_task, goal_context_from_metadata
from core.utils.hash import hash_file_bytes
from core.vault_state.identity import resolve_or_create_vault_identity
from core.vault_state.models import TaskFileMutation
from core.vault_state.pathing import normalize_vault_relative_path, resolve_vault_relative_path
from core.vault_state.service import VaultStateService
from core.vault_state.snapshots import (
    compute_snapshot_expiration,
    compute_task_mutation_expiration,
    ensure_task_file_snapshot,
)


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
    related_path: str | None
    operation: str
    before_exists: bool
    before_hash: str | None
    after_exists: bool
    after_hash: str | None
    task_id: str | None
    event_sequence: int | None
    before_snapshot_id: int | None
    snapshot_ref: str | None


@dataclass(frozen=True)
class DirectoryCleanupResult:
    """Result of a best-effort empty-directory cleanup inside a vault."""

    vault_id: str
    vault_name: str
    path: str
    removed_paths: tuple[str, ...]
    skipped_paths: tuple[str, ...]
    after_exists: bool
    task_id: str | None
    event_sequence: int | None


def write_vault_file(
    *,
    vault_path: str | Path,
    path: str,
    content: str,
    fail_if_exists: bool = True,
    markdown_only: bool = False,
    warn_without_task: bool = True,
) -> RecordedMutationResult:
    """Create or overwrite a vault file while recording task mutation metadata."""
    return mutate_vault_file(
        vault_path=vault_path,
        path=path,
        operation="write",
        mutator=lambda full_path: full_path.write_text(content, encoding="utf-8"),
        fail_if_exists=fail_if_exists,
        markdown_only=markdown_only,
        create_parent=True,
        warn_without_task=warn_without_task,
    )


def write_vault_file_bytes(
    *,
    vault_path: str | Path,
    path: str,
    content: bytes,
    fail_if_exists: bool = True,
    warn_without_task: bool = True,
) -> RecordedMutationResult:
    """Create or overwrite a binary vault file while recording mutation metadata."""
    return mutate_vault_file(
        vault_path=vault_path,
        path=path,
        operation="write",
        mutator=lambda full_path: full_path.write_bytes(content),
        fail_if_exists=fail_if_exists,
        create_parent=True,
        warn_without_task=warn_without_task,
    )


def append_vault_file(
    *,
    vault_path: str | Path,
    path: str,
    content: str,
    markdown_only: bool = False,
) -> RecordedMutationResult:
    """Append text to an existing vault file while recording mutation metadata."""

    def append_content(full_path: Path) -> None:
        with full_path.open("a", encoding="utf-8") as file:
            file.write(content)

    return mutate_vault_file(
        vault_path=vault_path,
        path=path,
        operation="append",
        mutator=append_content,
        require_exists=True,
        markdown_only=markdown_only,
    )


def replace_vault_file_content(
    *,
    vault_path: str | Path,
    path: str,
    content: str,
    operation: str,
    markdown_only: bool = False,
) -> RecordedMutationResult:
    """Replace the full contents of an existing vault file and record the mutation."""

    def write_content(full_path: Path) -> None:
        full_path.write_text(content, encoding="utf-8")

    return mutate_vault_file(
        vault_path=vault_path,
        path=path,
        operation=operation,
        mutator=write_content,
        require_exists=True,
        markdown_only=markdown_only,
    )


def delete_vault_file(
    *,
    vault_path: str | Path,
    path: str,
    markdown_only: bool = False,
    warn_without_task: bool = True,
) -> RecordedMutationResult:
    """Delete an existing vault file while recording mutation metadata."""
    return mutate_vault_file(
        vault_path=vault_path,
        path=path,
        operation="delete",
        mutator=lambda full_path: os.remove(full_path),
        require_exists=True,
        markdown_only=markdown_only,
        warn_without_task=warn_without_task,
    )


def delete_empty_vault_directory_tree(
    *,
    vault_path: str | Path,
    path: str,
) -> DirectoryCleanupResult:
    """Delete empty directories under ``path`` and leave non-empty dirs in place."""
    vault_root = Path(vault_path).resolve()
    relative_path = normalize_vault_relative_path(path)
    if not relative_path:
        raise VaultMutationRejected(
            "invalid_target",
            "Cannot delete the vault root directory.",
        )
    full_path = resolve_vault_relative_path(
        vault_path=vault_root,
        path=relative_path,
        markdown_only=False,
    )
    if not full_path.exists():
        raise VaultMutationRejected(
            "directory_not_found",
            f"Cannot delete '{relative_path}' - directory does not exist.",
        )
    if not full_path.is_dir():
        raise VaultMutationRejected(
            "not_directory",
            f"Cannot delete '{relative_path}' as a directory - target is not a directory.",
        )

    identity = resolve_or_create_vault_identity(vault_root)
    vault_name = vault_root.name
    task = get_current_execution_task()
    service = VaultStateService()
    removed_paths: list[str] = []

    for root, _dirs, _files in os.walk(full_path, topdown=False):
        directory = Path(root)
        try:
            directory.rmdir()
        except OSError:
            continue
        removed_paths.append(_relative_to_vault(vault_root, directory))

    skipped_paths = _remaining_directory_paths(vault_root, full_path)
    event_sequence = None
    if removed_paths:
        refresh = service.refresh_vault(vault_root, vault_name=vault_name)
        event_sequence = refresh.latest_sequence

    result = DirectoryCleanupResult(
        vault_id=identity.vault_id,
        vault_name=vault_name,
        path=relative_path,
        removed_paths=tuple(sorted(removed_paths)),
        skipped_paths=tuple(skipped_paths),
        after_exists=full_path.exists(),
        task_id=task.task_id if task is not None else None,
        event_sequence=event_sequence,
    )
    logger.add_sink("validation").info(
        "vault_empty_directory_cleanup_completed",
        data={
            "event": "vault_empty_directory_cleanup_completed",
            "task_id": result.task_id,
            "vault_id": result.vault_id,
            "vault_name": result.vault_name,
            "path": result.path,
            "removed_count": len(result.removed_paths),
            "skipped_count": len(result.skipped_paths),
            "after_exists": result.after_exists,
            "event_sequence": result.event_sequence,
        },
    )
    return result


def move_vault_file(
    *,
    vault_path: str | Path,
    path: str,
    destination: str,
    overwrite: bool = False,
    markdown_only: bool = False,
) -> tuple[RecordedMutationResult, RecordedMutationResult]:
    """Move a vault file while recording source and destination file mutations."""
    vault_root = Path(vault_path).resolve()
    source_relative = normalize_vault_relative_path(path)
    destination_relative = normalize_vault_relative_path(destination)
    source_path = resolve_vault_relative_path(
        vault_path=vault_root,
        path=source_relative,
        markdown_only=markdown_only,
    )
    destination_path = resolve_vault_relative_path(
        vault_path=vault_root,
        path=destination_relative,
        markdown_only=markdown_only,
    )
    if not source_path.exists():
        raise VaultMutationRejected(
            "source_not_found",
            f"Cannot move '{source_relative}' - source file does not exist.",
        )
    if destination_path.exists() and not overwrite:
        raise VaultMutationRejected(
            "destination_exists",
            f"Cannot move '{source_relative}' - destination file already exists.",
        )

    source_before_hash = hash_file_bytes(source_path, length=None)
    destination_before_exists = destination_path.exists()
    destination_before_hash = (
        hash_file_bytes(destination_path, length=None) if destination_before_exists else None
    )
    identity = resolve_or_create_vault_identity(vault_root)
    vault_name = vault_root.name
    task = get_current_execution_task()
    service = VaultStateService()
    created_at = datetime.now(UTC)
    snapshot_expires_at = compute_snapshot_expiration(created_at)
    mutation_expires_at = compute_task_mutation_expiration(created_at)
    source_snapshot_ref = None
    source_snapshot_id = None
    destination_snapshot_ref = None
    destination_snapshot_id = None

    stage = "snapshot"
    try:
        if task is not None:
            with service.SessionFactory() as session:
                source_snapshot = ensure_task_file_snapshot(
                    session=session,
                    task_id=task.task_id,
                    task_kind=task.kind,
                    task_source=task.source,
                    task_scope=task.scope,
                    task_label=task.label,
                    vault_id=identity.vault_id,
                    vault_name=vault_name,
                    vault_root=vault_root,
                    relative_path=source_relative,
                    before_exists=True,
                    source_path=source_path,
                    purpose="rollback",
                    source="task_mutation_before",
                    scope_kind="task",
                    scope_id=task.task_id,
                    created_at=created_at,
                    expires_at=snapshot_expires_at,
                )
                source_snapshot_ref = source_snapshot.snapshot_ref
                source_snapshot_id = source_snapshot.file_snapshot_id
                destination_snapshot = ensure_task_file_snapshot(
                    session=session,
                    task_id=task.task_id,
                    task_kind=task.kind,
                    task_source=task.source,
                    task_scope=task.scope,
                    task_label=task.label,
                    vault_id=identity.vault_id,
                    vault_name=vault_name,
                    vault_root=vault_root,
                    relative_path=destination_relative,
                    before_exists=destination_before_exists,
                    source_path=destination_path,
                    purpose="rollback",
                    source="task_mutation_before",
                    scope_kind="task",
                    scope_id=task.task_id,
                    created_at=created_at,
                    expires_at=snapshot_expires_at,
                )
                destination_snapshot_ref = destination_snapshot.snapshot_ref
                destination_snapshot_id = destination_snapshot.file_snapshot_id
                session.commit()

        stage = "mutate"
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source_path, destination_path)

        destination_after_hash = hash_file_bytes(destination_path, length=None)
        stage = "refresh"
        refresh = service.refresh_vault(vault_root, vault_name=vault_name)
        event_sequence = refresh.latest_sequence

        source_result = RecordedMutationResult(
            vault_id=identity.vault_id,
            vault_name=vault_name,
            path=source_relative,
            related_path=destination_relative,
            operation="move",
            before_exists=True,
            before_hash=source_before_hash,
            after_exists=source_path.exists(),
            after_hash=hash_file_bytes(source_path, length=None) if source_path.exists() else None,
            task_id=task.task_id if task is not None else None,
            event_sequence=event_sequence,
            before_snapshot_id=source_snapshot_id,
            snapshot_ref=source_snapshot_ref,
        )
        destination_result = RecordedMutationResult(
            vault_id=identity.vault_id,
            vault_name=vault_name,
            path=destination_relative,
            related_path=source_relative,
            operation="move",
            before_exists=destination_before_exists,
            before_hash=destination_before_hash,
            after_exists=True,
            after_hash=destination_after_hash,
            task_id=task.task_id if task is not None else None,
            event_sequence=event_sequence,
            before_snapshot_id=destination_snapshot_id,
            snapshot_ref=destination_snapshot_ref,
        )
        stage = "persist"
        _persist_or_log_mutation(
            service=service,
            task=task,
            result=source_result,
            created_at=created_at,
            expires_at=mutation_expires_at,
        )
        _persist_or_log_mutation(
            service=service,
            task=task,
            result=destination_result,
            created_at=created_at,
            expires_at=mutation_expires_at,
        )
    except Exception as exc:
        _log_mutation_failed(
            task=task,
            vault_id=identity.vault_id,
            vault_name=vault_name,
            path=source_relative,
            related_path=destination_relative,
            operation="move",
            stage=stage,
            before_exists=True,
            before_hash=source_before_hash,
            before_snapshot_id=source_snapshot_id,
            error=exc,
        )
        raise
    return source_result, destination_result


def mutate_vault_file(
    *,
    vault_path: str | Path,
    path: str,
    operation: str,
    mutator: Callable[[Path], object],
    require_exists: bool = False,
    fail_if_exists: bool = False,
    markdown_only: bool = False,
    create_parent: bool = False,
    warn_without_task: bool = True,
) -> RecordedMutationResult:
    """Mutate one vault file while recording task-scoped mutation metadata."""
    vault_root = Path(vault_path).resolve()
    relative_path = normalize_vault_relative_path(path)
    full_path = resolve_vault_relative_path(
        vault_path=vault_root,
        path=relative_path,
        markdown_only=markdown_only,
    )
    before_exists = full_path.exists()
    if require_exists and not before_exists:
        raise VaultMutationRejected(
            "file_not_found",
            f"Cannot mutate '{relative_path}' - file does not exist.",
        )
    if before_exists and fail_if_exists:
        raise VaultMutationRejected(
            "file_exists",
            f"Cannot mutate '{relative_path}' - file already exists.",
        )
    before_hash = hash_file_bytes(full_path, length=None) if before_exists else None
    identity = resolve_or_create_vault_identity(vault_root)
    vault_name = vault_root.name
    task = get_current_execution_task()
    service = VaultStateService()
    snapshot_ref = None
    before_snapshot_id = None
    created_at = datetime.now(UTC)
    snapshot_expires_at = compute_snapshot_expiration(created_at)
    mutation_expires_at = compute_task_mutation_expiration(created_at)

    stage = "snapshot"
    try:
        if task is not None:
            with service.SessionFactory() as session:
                snapshot = ensure_task_file_snapshot(
                    session=session,
                    task_id=task.task_id,
                    task_kind=task.kind,
                    task_source=task.source,
                    task_scope=task.scope,
                    task_label=task.label,
                    vault_id=identity.vault_id,
                    vault_name=vault_name,
                    vault_root=vault_root,
                    relative_path=relative_path,
                    before_exists=before_exists,
                    source_path=full_path,
                    purpose="rollback",
                    source="task_mutation_before",
                    scope_kind="task",
                    scope_id=task.task_id,
                    created_at=created_at,
                    expires_at=snapshot_expires_at,
                )
                snapshot_ref = snapshot.snapshot_ref
                before_snapshot_id = snapshot.file_snapshot_id
                session.commit()

        stage = "mutate"
        if create_parent:
            full_path.parent.mkdir(parents=True, exist_ok=True)
        mutator(full_path)

        after_exists = full_path.exists()
        after_hash = hash_file_bytes(full_path, length=None) if after_exists else None

        stage = "refresh"
        refresh = service.refresh_vault(vault_root, vault_name=vault_name)
        event_sequence = refresh.latest_sequence
        result = RecordedMutationResult(
            vault_id=identity.vault_id,
            vault_name=vault_name,
            path=relative_path,
            related_path=None,
            operation=operation,
            before_exists=before_exists,
            before_hash=before_hash,
            after_exists=after_exists,
            after_hash=after_hash,
            task_id=task.task_id if task is not None else None,
            event_sequence=event_sequence,
            before_snapshot_id=before_snapshot_id,
            snapshot_ref=snapshot_ref,
        )

        stage = "persist"
        _persist_or_log_mutation(
            service=service,
            task=task,
            result=result,
            created_at=created_at,
            expires_at=mutation_expires_at,
            warn_without_task=warn_without_task,
        )
    except Exception as exc:
        _log_mutation_failed(
            task=task,
            vault_id=identity.vault_id,
            vault_name=vault_name,
            path=relative_path,
            related_path=None,
            operation=operation,
            stage=stage,
            before_exists=before_exists,
            before_hash=before_hash,
            before_snapshot_id=before_snapshot_id,
            error=exc,
        )
        raise
    return result


def _log_mutation_failed(
    *,
    task: Any,
    vault_id: str,
    vault_name: str,
    path: str,
    related_path: str | None,
    operation: str,
    stage: str,
    before_exists: bool,
    before_hash: str | None,
    before_snapshot_id: int | None,
    error: Exception,
) -> None:
    """Log an unexpected failure in the shared vault mutation path."""
    logger.add_sink("validation").warning(
        "vault_state_mutation_failed",
        data={
            "event": "vault_state_mutation_failed",
            "task_id": task.task_id if task is not None else None,
            "task_kind": task.kind if task is not None else None,
            "task_source": task.source if task is not None else None,
            "task_scope": task.scope if task is not None else None,
            "task_label": task.label if task is not None else None,
            "vault_id": vault_id,
            "vault_name": vault_name,
            "path": path,
            "related_path": related_path,
            "operation": operation,
            "stage": stage,
            "before_exists": before_exists,
            "before_hash": before_hash,
            "before_snapshot_id": before_snapshot_id,
            "error_type": type(error).__name__,
            "error": str(error),
        },
    )


def _remaining_directory_paths(vault_root: Path, target: Path) -> tuple[str, ...]:
    """Return directories still present under target after cleanup."""
    if not target.exists() or not target.is_dir():
        return ()
    paths = [_relative_to_vault(vault_root, target)]
    for root, dirs, _files in os.walk(target):
        root_path = Path(root)
        for directory_name in dirs:
            paths.append(_relative_to_vault(vault_root, root_path / directory_name))
    return tuple(sorted(paths))


def _relative_to_vault(vault_root: Path, path: Path) -> str:
    return normalize_vault_relative_path(path.relative_to(vault_root))


def _persist_or_log_mutation(
    *,
    service: VaultStateService,
    task,
    result: RecordedMutationResult,
    created_at: datetime,
    expires_at: datetime | None,
    warn_without_task: bool = True,
) -> None:
    """Persist a mutation row when task context exists, otherwise log it as untracked."""
    if task is None:
        if not warn_without_task:
            return
        logger.add_sink("validation").warning(
            "vault_state_mutation_untracked",
            data={
                "event": "vault_state_mutation_untracked",
                "vault_id": result.vault_id,
                "vault_name": result.vault_name,
                "path": result.path,
                "related_path": result.related_path,
                "operation": result.operation,
                "reason": "missing_execution_task_context",
            },
        )
        return

    with service.SessionFactory() as session:
        goal_id, step_id = goal_context_from_metadata(getattr(task, "metadata", None))
        session.add(
            TaskFileMutation(
                task_id=task.task_id,
                task_kind=task.kind,
                task_source=task.source,
                task_scope=task.scope,
                task_label=task.label,
                goal_id=goal_id,
                step_id=step_id,
                vault_id=result.vault_id,
                vault_name=result.vault_name,
                path=result.path,
                related_path=result.related_path,
                operation=result.operation,
                event_sequence=result.event_sequence,
                before_exists=result.before_exists,
                before_hash=result.before_hash,
                before_snapshot_id=result.before_snapshot_id,
                after_exists=result.after_exists,
                after_hash=result.after_hash,
                after_snapshot_id=None,
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
            "goal_id": goal_id,
            "step_id": step_id,
            "vault_id": result.vault_id,
            "vault_name": result.vault_name,
            "path": result.path,
            "related_path": result.related_path,
            "operation": result.operation,
            "before_exists": result.before_exists,
            "after_exists": result.after_exists,
            "before_hash": result.before_hash,
            "after_hash": result.after_hash,
            "before_snapshot_id": result.before_snapshot_id,
            "event_sequence": result.event_sequence,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "snapshot_ref": result.snapshot_ref,
        },
    )
