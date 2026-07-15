"""State-based planning and execution for explicit activity rollback."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable
import uuid

from sqlalchemy import select

from core.logger import UnifiedLogger
from core.utils.hash import hash_file_bytes
from core.vault_state.activity import VaultActivityContext, use_vault_activity
from core.vault_state.file_mutations import FileStateRestore, restore_vault_file_states
from core.vault_state.identity import resolve_or_create_vault_identity
from core.vault_state.models import FileSnapshot, VaultActivity, VaultMutation
from core.vault_state.pathing import resolve_vault_relative_path
from core.vault_state.service import VaultStateService

logger = UnifiedLogger(tag="vault-activity-rollback")


@dataclass(frozen=True)
class ActivityRollbackIssue:
    """One reason an activity cannot currently be rolled back."""

    code: str
    message: str
    path: str | None = None


@dataclass(frozen=True)
class ActivityRollbackPath:
    """One exact path transition in an activity rollback plan."""

    path: str
    expected_exists: bool
    expected_sha256: str | None
    restore_exists: bool
    restore_sha256: str | None
    snapshot_id: int | None
    snapshot_path: Path | None

    @property
    def action(self) -> str:
        return "restore" if self.restore_exists else "delete"


@dataclass(frozen=True)
class ActivityRollbackPlan:
    """Current rollback availability and desired states for one activity."""

    activity_id: str
    activity_label: str
    activity_status: str
    vault_id: str
    vault_name: str
    can_rollback: bool
    paths: tuple[ActivityRollbackPath, ...]
    issues: tuple[ActivityRollbackIssue, ...]

    @property
    def restore_count(self) -> int:
        return sum(path.restore_exists for path in self.paths)

    @property
    def delete_count(self) -> int:
        return sum(not path.restore_exists for path in self.paths)


@dataclass(frozen=True)
class ActivityRollbackResult:
    """Outcome of one completed explicit activity rollback."""

    source_activity_id: str
    rollback_activity_id: str
    vault_name: str
    restored_count: int
    deleted_count: int


class ActivityRollbackUnavailable(Exception):
    """Raised when preflight rejects a requested activity rollback."""

    def __init__(self, plan: ActivityRollbackPlan) -> None:
        super().__init__("Activity rollback is not currently available.")
        self.plan = plan


def preview_activity_rollback(
    *,
    vault_path: str | Path,
    activity_id: str,
) -> ActivityRollbackPlan:
    """Build a state-based rollback plan without changing the filesystem."""
    vault_root = Path(vault_path).resolve()
    service = VaultStateService()
    now = datetime.now(UTC)
    issues: list[ActivityRollbackIssue] = []
    paths: list[ActivityRollbackPath] = []

    with service.SessionFactory() as session:
        activity = session.get(VaultActivity, activity_id)
        if activity is None or activity.vault_name != vault_root.name:
            raise LookupError(f"Vault activity not found: {activity_id}")
        rows = list(
            session.scalars(
                select(VaultMutation)
                .where(VaultMutation.activity_id == activity_id)
                .order_by(VaultMutation.created_at.asc(), VaultMutation.id.asc())
            )
        )
        snapshots = {
            snapshot.id: snapshot
            for snapshot in session.scalars(
                select(FileSnapshot).where(
                    FileSnapshot.id.in_(
                        [
                            row.before_snapshot_id
                            for row in rows
                            if row.before_snapshot_id
                        ]
                    )
                )
            )
        }

    current_identity = resolve_or_create_vault_identity(vault_root)
    if current_identity.vault_id != activity.vault_id:
        issues.append(
            ActivityRollbackIssue(
                code="vault_identity_mismatch",
                message="This activity belongs to an earlier vault with the same name.",
            )
        )
    if activity.status == "running":
        issues.append(
            ActivityRollbackIssue(
                code="activity_in_progress",
                message="This activity is still in progress.",
            )
        )
    if _is_expired(activity.expires_at, now) or any(
        _is_expired(row.expires_at, now) for row in rows
    ):
        issues.append(
            ActivityRollbackIssue(
                code="activity_expired",
                message="This activity is outside its retained rollback window.",
            )
        )
    if activity.rollback_status == "completed":
        issues.append(
            ActivityRollbackIssue(
                code="already_rolled_back",
                message="This activity has already been rolled back.",
            )
        )
    if not rows:
        issues.append(
            ActivityRollbackIssue(
                code="no_mutations",
                message="This activity has no retained mutations to roll back.",
            )
        )
    if any(row.target_kind != "file" for row in rows):
        issues.append(
            ActivityRollbackIssue(
                code="unsupported_directory_operation",
                message="Directory operations do not retain enough state for full rollback.",
            )
        )
    if any(row.status != "completed" for row in rows):
        issues.append(
            ActivityRollbackIssue(
                code="incomplete_mutation",
                message="This activity contains a mutation without a completed outcome.",
            )
        )

    for path, path_rows in _group_rows_by_path(rows):
        first = path_rows[0]
        last = path_rows[-1]
        snapshot_path: Path | None = None
        snapshot_id = first.before_snapshot_id
        if first.before_exists:
            snapshot = snapshots.get(snapshot_id) if snapshot_id is not None else None
            if snapshot is None or _is_expired(snapshot.expires_at, now):
                issues.append(
                    ActivityRollbackIssue(
                        code="snapshot_unavailable",
                        message=f"The retained state for '{path}' is no longer available.",
                        path=path,
                    )
                )
            else:
                resolved = service.resolve_snapshot_file(snapshot.id)
                if resolved is None or not resolved.path.is_file():
                    issues.append(
                        ActivityRollbackIssue(
                            code="snapshot_unavailable",
                            message=f"The retained state for '{path}' is no longer available.",
                            path=path,
                        )
                    )
                elif hash_file_bytes(resolved.path, length=None) != first.before_hash:
                    issues.append(
                        ActivityRollbackIssue(
                            code="snapshot_invalid",
                            message=f"The retained state for '{path}' failed integrity checking.",
                            path=path,
                        )
                    )
                else:
                    snapshot_path = resolved.path

        full_path = resolve_vault_relative_path(
            vault_path=vault_root,
            path=path,
            markdown_only=False,
        )
        actual_exists = full_path.exists()
        actual_hash = (
            hash_file_bytes(full_path, length=None)
            if actual_exists and full_path.is_file()
            else None
        )
        if actual_exists != bool(last.after_exists) or actual_hash != last.after_hash:
            issues.append(
                ActivityRollbackIssue(
                    code="state_conflict",
                    message=f"'{path}' has changed since this activity completed.",
                    path=path,
                )
            )
        paths.append(
            ActivityRollbackPath(
                path=path,
                expected_exists=bool(last.after_exists),
                expected_sha256=last.after_hash,
                restore_exists=bool(first.before_exists),
                restore_sha256=first.before_hash,
                snapshot_id=snapshot_id,
                snapshot_path=snapshot_path,
            )
        )

    return ActivityRollbackPlan(
        activity_id=activity.activity_id,
        activity_label=activity.label,
        activity_status=activity.status,
        vault_id=activity.vault_id,
        vault_name=activity.vault_name,
        can_rollback=not issues,
        paths=tuple(paths),
        issues=tuple(_deduplicate_issues(issues)),
    )


def execute_activity_rollback(
    *,
    vault_path: str | Path,
    activity_id: str,
    expected_states: Iterable[tuple[str, bool, str | None]],
) -> ActivityRollbackResult:
    """Execute one preflighted activity rollback as a new durable activity."""
    vault_root = Path(vault_path).resolve()
    plan = preview_activity_rollback(vault_path=vault_root, activity_id=activity_id)
    expected_state_items = tuple(expected_states)
    expected_state_map = _expected_state_map(expected_state_items)
    if (
        not plan.can_rollback
        or len(expected_state_map) != len(expected_state_items)
        or expected_state_map
        != {
            path.path: (path.expected_exists, path.expected_sha256)
            for path in plan.paths
        }
    ):
        logger.info(
            "Vault activity rollback rejected",
            data={
                "event": "vault_activity_rollback_rejected",
                "status": "skipped",
                "source_activity_id": activity_id,
                "vault_id": plan.vault_id,
                "vault_name": plan.vault_name,
                "reason_codes": [issue.code for issue in plan.issues],
            },
        )
        raise ActivityRollbackUnavailable(plan)

    rollback_activity_id = f"activity_{uuid.uuid4().hex}"
    context = VaultActivityContext(
        activity_id=rollback_activity_id,
        kind="explorer",
        source="api",
        scope=None,
        label=f"Rollback: {plan.activity_label}",
    )
    service = VaultStateService()
    states = tuple(
        FileStateRestore(
            path=path.path,
            content=path.snapshot_path.read_bytes() if path.snapshot_path else None,
            expected_exists=path.expected_exists,
            expected_sha256=path.expected_sha256,
        )
        for path in plan.paths
    )
    service.ensure_activity(
        context=context,
        vault_path=vault_root,
        vault_name=plan.vault_name,
    )
    service.update_activity_metadata(
        activity_id=rollback_activity_id,
        metadata={"source_activity_id": activity_id},
    )
    logger.info(
        "Vault activity rollback started",
        data={
            "event": "vault_activity_rollback_started",
            "status": "running",
            "source_activity_id": activity_id,
            "rollback_activity_id": rollback_activity_id,
            "vault_id": plan.vault_id,
            "vault_name": plan.vault_name,
            "path_count": len(plan.paths),
        },
    )
    with use_vault_activity(context):
        try:
            restore_vault_file_states(
                vault_path=vault_root,
                states=states,
                operation="rollback_activity",
                metadata={"source_activity_id": activity_id},
            )
        except Exception as exc:
            service.finish_activity(activity_id=rollback_activity_id, status="failed")
            logger.error(
                "Vault activity rollback failed",
                data={
                    "event": "vault_activity_rollback_failed",
                    "status": "failed",
                    "source_activity_id": activity_id,
                    "rollback_activity_id": rollback_activity_id,
                    "vault_id": plan.vault_id,
                    "vault_name": plan.vault_name,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            raise

    service.finish_activity(activity_id=rollback_activity_id, status="completed")
    service.set_activity_rollback_status(
        activity_id=activity_id,
        rollback_status="completed",
    )
    logger.add_sink("validation").info(
        "Vault activity rollback completed",
        data={
            "event": "vault_activity_rollback_completed",
            "status": "completed",
            "source_activity_id": activity_id,
            "rollback_activity_id": rollback_activity_id,
            "vault_id": plan.vault_id,
            "vault_name": plan.vault_name,
            "restored_count": plan.restore_count,
            "deleted_count": plan.delete_count,
        },
    )
    return ActivityRollbackResult(
        source_activity_id=activity_id,
        rollback_activity_id=rollback_activity_id,
        vault_name=plan.vault_name,
        restored_count=plan.restore_count,
        deleted_count=plan.delete_count,
    )


def _group_rows_by_path(
    rows: Iterable[VaultMutation],
) -> tuple[tuple[str, tuple[VaultMutation, ...]], ...]:
    grouped: dict[str, list[VaultMutation]] = {}
    for row in rows:
        if row.target_kind == "file":
            grouped.setdefault(row.path, []).append(row)
    return tuple((path, tuple(grouped[path])) for path in sorted(grouped))


def _expected_state_map(
    states: Iterable[tuple[str, bool, str | None]],
) -> dict[str, tuple[bool, str | None]]:
    return {path: (exists, sha256) for path, exists, sha256 in states}


def _is_expired(value: datetime | None, now: datetime) -> bool:
    if value is None:
        return False
    normalized = (
        value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    )
    return normalized < now


def _deduplicate_issues(
    issues: Iterable[ActivityRollbackIssue],
) -> tuple[ActivityRollbackIssue, ...]:
    unique: dict[tuple[str, str | None], ActivityRollbackIssue] = {}
    for issue in issues:
        unique.setdefault((issue.code, issue.path), issue)
    return tuple(unique.values())
