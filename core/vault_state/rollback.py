"""Task-scoped vault mutation rollback."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import shutil

from core.logger import UnifiedLogger
from core.runtime.execution_tasks import ExecutionTaskSnapshot
from core.runtime.state import get_runtime_context
from core.settings import get_task_rollback_enabled
from core.vault_state.models import TaskFileMutation, TaskSnapshot
from core.vault_state.pathing import resolve_vault_relative_path
from core.vault_state.service import VaultStateService


logger = UnifiedLogger(tag="vault-rollback")

ROLLBACK_TRIGGER_STATUSES = frozenset({"failed", "cancelled", "timed_out"})


@dataclass(frozen=True)
class TaskRollbackResult:
    """Summary of a task rollback attempt."""

    task_id: str
    status: str
    skipped: bool
    reason: str | None
    mutation_rows_seen: int
    paths_restored: int
    paths_deleted: int
    vaults_refreshed: int


def handle_task_terminal_for_rollback(snapshot: ExecutionTaskSnapshot) -> None:
    """TaskCoordinator terminal observer for rollback-triggering task states."""
    status = str(snapshot.status or "").strip().lower()
    if status not in ROLLBACK_TRIGGER_STATUSES:
        return
    try:
        rollback_task_file_mutations(
            task_id=snapshot.task_id,
            terminal_status=status,
            reason=snapshot.terminal_reason,
        )
    except Exception as exc:  # noqa: BLE001
        logger.add_sink("validation").error(
            "task_rollback_failed",
            data={
                "event": "task_rollback_failed",
                "task_id": snapshot.task_id,
                "terminal_status": status,
                "reason": snapshot.terminal_reason,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )


def rollback_task_file_mutations(
    *,
    task_id: str,
    terminal_status: str,
    reason: str | None = None,
) -> TaskRollbackResult:
    """Rollback retained file mutations for one terminal task when policy requires it."""
    status = str(terminal_status or "").strip().lower()
    if status not in ROLLBACK_TRIGGER_STATUSES:
        return _skipped_result(task_id=task_id, status=status, reason="status_not_rollbackable")
    if not get_task_rollback_enabled():
        return _skipped_result(task_id=task_id, status=status, reason="task_rollback_disabled")

    service = VaultStateService()
    now = datetime.now(UTC)
    paths_restored = 0
    paths_deleted = 0
    refreshed_vaults: set[tuple[str, str]] = set()

    with service.SessionFactory() as session:
        rows = (
            session.query(TaskFileMutation)
            .filter(TaskFileMutation.task_id == task_id)
            .order_by(TaskFileMutation.id.asc())
            .all()
        )
        if not rows:
            return _skipped_result(task_id=task_id, status=status, reason="no_mutations")
        snapshots = session.query(TaskSnapshot).filter(TaskSnapshot.task_id == task_id).all()
        if snapshots and all(snapshot.status == "rolled_back" for snapshot in snapshots):
            result = _skipped_result(
                task_id=task_id,
                status=status,
                reason="already_rolled_back",
                mutation_rows_seen=len(rows),
            )
            logger.add_sink("validation").info(
                "task_rollback_skipped",
                data={
                    "event": "task_rollback_skipped",
                    "task_id": task_id,
                    "terminal_status": status,
                    "reason": result.reason,
                    "mutation_rows_seen": result.mutation_rows_seen,
                },
            )
            return result

        logger.add_sink("validation").info(
            "task_rollback_started",
            data={
                "event": "task_rollback_started",
                "task_id": task_id,
                "terminal_status": status,
                "reason": reason,
                "mutation_rows_seen": len(rows),
            },
        )

        grouped = _mutation_groups(rows)
        for group in sorted(grouped.values(), key=lambda item: item[-1].id, reverse=True):
            first = group[0]
            snapshot = session.get(TaskSnapshot, (task_id, first.vault_id))
            vault_root = _vault_root(first.vault_name)
            target_path = resolve_vault_relative_path(vault_path=vault_root, path=first.path)
            if first.before_exists:
                _restore_snapshot_file(snapshot=snapshot, mutation=first, target_path=target_path)
                paths_restored += 1
                logger.add_sink("validation").info(
                    "task_rollback_file_restored",
                    data={
                        "event": "task_rollback_file_restored",
                        "task_id": task_id,
                        "vault_id": first.vault_id,
                        "vault_name": first.vault_name,
                        "path": first.path,
                        "snapshot_ref": first.snapshot_ref,
                    },
                )
            else:
                if target_path.exists():
                    target_path.unlink()
                    paths_deleted += 1
                logger.add_sink("validation").info(
                    "task_rollback_file_deleted",
                    data={
                        "event": "task_rollback_file_deleted",
                        "task_id": task_id,
                        "vault_id": first.vault_id,
                        "vault_name": first.vault_name,
                        "path": first.path,
                    },
                )
            refreshed_vaults.add((first.vault_name, str(vault_root)))

        for snapshot in snapshots:
            snapshot.status = "rolled_back"
            snapshot.rolled_back_at = now
        session.commit()

    vaults_refreshed = 0
    for vault_name, vault_root in sorted(refreshed_vaults):
        service.refresh_vault(vault_root, vault_name=vault_name)
        vaults_refreshed += 1

    result = TaskRollbackResult(
        task_id=task_id,
        status=status,
        skipped=False,
        reason=reason,
        mutation_rows_seen=len(rows),
        paths_restored=paths_restored,
        paths_deleted=paths_deleted,
        vaults_refreshed=vaults_refreshed,
    )
    logger.add_sink("validation").info(
        "task_rollback_completed",
        data={
            "event": "task_rollback_completed",
            "task_id": task_id,
            "terminal_status": status,
            "reason": reason,
            "mutation_rows_seen": result.mutation_rows_seen,
            "paths_restored": result.paths_restored,
            "paths_deleted": result.paths_deleted,
            "vaults_refreshed": result.vaults_refreshed,
        },
    )
    return result


def _mutation_groups(rows: list[TaskFileMutation]) -> dict[tuple[str, str], list[TaskFileMutation]]:
    grouped: dict[tuple[str, str], list[TaskFileMutation]] = {}
    for row in rows:
        grouped.setdefault((row.vault_id, row.path), []).append(row)
    return grouped


def _restore_snapshot_file(
    *,
    snapshot: TaskSnapshot | None,
    mutation: TaskFileMutation,
    target_path: Path,
) -> None:
    if snapshot is None:
        raise RuntimeError(
            f"Cannot rollback '{mutation.path}' for task '{mutation.task_id}': missing task snapshot"
        )
    if not mutation.snapshot_ref:
        raise RuntimeError(
            f"Cannot rollback '{mutation.path}' for task '{mutation.task_id}': missing snapshot ref"
        )
    snapshot_path = (Path(snapshot.snapshot_root) / mutation.snapshot_ref).resolve()
    if not snapshot_path.exists() or not snapshot_path.is_file():
        raise RuntimeError(
            f"Cannot rollback '{mutation.path}' for task '{mutation.task_id}': snapshot file missing"
        )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(snapshot_path, target_path)


def _vault_root(vault_name: str) -> Path:
    runtime = get_runtime_context()
    vault_info = runtime.workflow_loader.get_vault_info()
    vault_path = (vault_info.get(vault_name) or {}).get("path")
    if not vault_path:
        raise RuntimeError(f"Cannot rollback task mutation: vault not found: {vault_name}")
    return Path(vault_path)


def _skipped_result(
    *,
    task_id: str,
    status: str,
    reason: str,
    mutation_rows_seen: int = 0,
) -> TaskRollbackResult:
    return TaskRollbackResult(
        task_id=task_id,
        status=status,
        skipped=True,
        reason=reason,
        mutation_rows_seen=mutation_rows_seen,
        paths_restored=0,
        paths_deleted=0,
        vaults_refreshed=0,
    )
