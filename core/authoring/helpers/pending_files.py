"""Definition and execution for the pending_files(...) Monty helper."""

from __future__ import annotations

from datetime import UTC, datetime
import difflib
import os
from pathlib import Path
from typing import Any

from sqlalchemy import select

from core.authoring.contracts import (
    AuthoringCapabilityCall,
    AuthoringCapabilityDefinition,
    AuthoringExecutionContext,
    PendingFilesResult,
    RetrievedItem,
    ScriptToolResult,
)
from core.authoring.helpers.common import build_capability
from core.authoring.helpers.runtime_common import coerce_tool_return_value_text
from core.logger import UnifiedLogger
from core.runtime.execution_tasks import get_current_execution_task
from core.utils.hash import hash_file_bytes, hash_file_content
from core.vault_state.identity import resolve_or_create_vault_identity
from core.vault_state.models import FileSnapshot, SnapshotSet
from core.vault_state.pathing import normalize_vault_relative_path
from core.vault_state.service import VaultStateService
from core.vault_state.snapshots import compute_snapshot_expiration, ensure_task_file_snapshot


logger = UnifiedLogger(tag="authoring-host")
PENDING_BASELINE_PURPOSE = "pending_complete"
PENDING_BASELINE_SOURCE = "pending_files.complete"


def build_definition() -> AuthoringCapabilityDefinition:
    return build_capability(
        name="pending_files",
        doc="Filter or complete workflow pending files.",
        contract=_contract(),
        handler=execute,
    )


async def execute(
    call: AuthoringCapabilityCall,
    context: AuthoringExecutionContext,
) -> PendingFilesResult:
    host = context.host
    operation, items = _parse_call(call)
    if not host.state_manager:
        raise ValueError("pending_files requires workflow file-state tracking to be available")
    if operation == "get":
        pending_items = _filter_pending_items(
            items,
            workflow_id=context.workflow_id,
            state_manager=host.state_manager,
            vault_path=host.vault_path or "",
        )
        logger.add_sink("validation").info(
            "authoring_pending_files_filtered",
            data={
                "workflow_id": context.workflow_id,
                "candidate_count": len(items),
                "pending_count": len(pending_items),
            },
        )
        return PendingFilesResult(
            operation="get",
            status="completed",
            items=tuple(pending_items),
        )
    if operation == "complete":
        file_records = _build_completion_records(items, vault_path=host.vault_path or "")
        snapshot_count = _capture_completion_baselines(
            items,
            workflow_id=context.workflow_id,
            vault_path=host.vault_path or "",
        )
        host.state_manager.mark_files_processed(file_records)
        logger.add_sink("validation").info(
            "authoring_pending_files_completed",
            data={
                "workflow_id": context.workflow_id,
                "completed_count": len(file_records),
                "snapshot_count": snapshot_count,
            },
        )
        return PendingFilesResult(
            operation="complete",
            status="completed",
            completed_count=len(file_records),
        )
    raise ValueError("pending_files operation must be one of: get, complete")


def _parse_call(
    call: AuthoringCapabilityCall,
) -> tuple[str, tuple[RetrievedItem, ...]]:
    if call.args:
        raise ValueError("pending_files only supports keyword arguments")
    unknown = sorted(set(call.kwargs) - {"operation", "items"})
    if unknown:
        raise ValueError(f"Unsupported pending_files arguments: {', '.join(unknown)}")
    operation = str(call.kwargs.get("operation") or "").strip().lower()
    if not operation:
        raise ValueError("pending_files requires a non-empty 'operation'")
    if "items" not in call.kwargs:
        raise ValueError("pending_files requires 'items'")
    items = _normalize_pending_items_input(call.kwargs.get("items"))
    return operation, items


def _normalize_pending_items_input(value: Any) -> tuple[RetrievedItem, ...]:
    if isinstance(value, ScriptToolResult):
        return _items_from_tool_result(value)
    if isinstance(value, RetrievedItem):
        return (value,)
    if isinstance(value, (list, tuple)):
        normalized: list[RetrievedItem] = []
        for item in value:
            if not isinstance(item, RetrievedItem):
                raise ValueError(
                    "pending_files items must be a file_ops_safe result, a RetrievedItem, "
                    "or a list/tuple of RetrievedItem values"
                )
            normalized.append(item)
        return tuple(normalized)
    raise ValueError(
        "pending_files items must be a file_ops_safe result, a RetrievedItem, "
        "or a list/tuple of RetrievedItem values"
    )


def _items_from_tool_result(result: ScriptToolResult) -> tuple[RetrievedItem, ...]:
    if result.metadata.get("tool_name") != "file_ops_safe":
        raise ValueError("pending_files only accepts ScriptToolResult values from file_ops_safe")
    paths = _extract_paths_from_file_ops_result(result)
    return tuple(
        RetrievedItem(
            ref=path,
            content="",
            exists=True,
            metadata={"source_path": path},
        )
        for path in paths
    )


def _extract_paths_from_file_ops_result(result: ScriptToolResult) -> tuple[str, ...]:
    metadata = dict(result.metadata or {})
    files = metadata.get("files")
    if isinstance(files, list):
        normalized = tuple(
            str(path).strip()
            for path in files
            if str(path).strip()
        )
        if normalized:
            return normalized

    matches = metadata.get("matches")
    if isinstance(matches, list):
        extracted: list[str] = []
        seen: set[str] = set()
        for raw_match in matches:
            if not isinstance(raw_match, str):
                continue
            candidate = raw_match.split(":", 1)[0].strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            extracted.append(candidate)
        if extracted:
            return tuple(extracted)

    return _extract_paths_from_file_ops_text(
        coerce_tool_return_value_text(result.return_value)
    )


def _extract_paths_from_file_ops_text(result_text: str) -> tuple[str, ...]:
    paths: list[str] = []
    seen: set[str] = set()
    for raw_line in str(result_text or "").splitlines():
        line = raw_line.strip()
        if line.startswith("📄 "):
            _icon, _space, candidate = line.partition(" ")
            candidate = candidate.strip()
        elif line.startswith("📁 "):
            continue
        elif ":" in line and not line.startswith(("Found ", "No matches", "Search error")):
            candidate = line.split(":", 1)[0].strip()
        else:
            continue
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        paths.append(candidate)
    if not paths:
        raise ValueError(
            "pending_files could not extract any file paths from the provided file_ops_safe result"
        )
    return tuple(paths)


def _filter_pending_items(
    items: tuple[RetrievedItem, ...],
    *,
    workflow_id: str,
    state_manager: Any,
    vault_path: str,
) -> list[RetrievedItem]:
    all_paths = [_resolve_item_path(item, vault_path=vault_path) for item in items]
    pending_paths = {
        os.path.realpath(path)
        for path in state_manager.get_pending_files(all_paths)
    }
    pending_items: list[RetrievedItem] = []
    for item in items:
        resolved_path = os.path.realpath(_resolve_item_path(item, vault_path=vault_path))
        if resolved_path not in pending_paths:
            continue
        pending_items.append(
            _with_pending_diff_metadata(
                item,
                workflow_id=workflow_id,
                vault_path=vault_path,
            )
        )
    return pending_items


def _with_pending_diff_metadata(
    item: RetrievedItem,
    *,
    workflow_id: str,
    vault_path: str,
) -> RetrievedItem:
    metadata = dict(item.metadata or {})
    metadata["pending_diff"] = _pending_diff_metadata(
        item,
        workflow_id=workflow_id,
        vault_path=vault_path,
    )
    return RetrievedItem(
        ref=item.ref,
        content=item.content,
        exists=item.exists,
        metadata=metadata,
    )


def _build_completion_records(
    items: tuple[RetrievedItem, ...],
    *,
    vault_path: str,
) -> list[dict[str, Any]]:
    if not items:
        raise ValueError("pending_files complete requires at least one item")
    file_records: list[dict[str, Any]] = []
    for item in items:
        source_path = _source_path_from_item(item)
        full_path = source_path if os.path.isabs(source_path) else os.path.join(vault_path, source_path)
        if os.path.isfile(full_path):
            content_hash = hash_file_bytes(full_path, length=None)
        elif item.content:
            content_hash = hash_file_content(item.content, length=None)
        else:
            raise ValueError("pending_files complete could not hash one or more selected items")
        file_records.append({"content_hash": content_hash, "filepath": source_path})
    return file_records


def _capture_completion_baselines(
    items: tuple[RetrievedItem, ...],
    *,
    workflow_id: str,
    vault_path: str,
) -> int:
    task = get_current_execution_task()
    if task is None:
        logger.add_sink("validation").warning(
            "pending_files_snapshot_skipped",
            data={
                "event": "pending_files_snapshot_skipped",
                "workflow_id": workflow_id,
                "reason": "missing_execution_task_context",
            },
        )
        return 0

    vault_root = Path(vault_path).resolve()
    identity = resolve_or_create_vault_identity(vault_root)
    vault_name = vault_root.name
    created_at = datetime.now(UTC)
    expires_at = compute_snapshot_expiration(created_at)
    service = VaultStateService()
    snapshot_count = 0

    with service.SessionFactory() as session:
        for item in items:
            full_path = Path(_resolve_item_path(item, vault_path=vault_path)).resolve()
            if not full_path.is_file():
                continue
            relative_path = _vault_relative_path(full_path, vault_root=vault_root)
            result = ensure_task_file_snapshot(
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
                before_exists=True,
                source_path=full_path,
                purpose=PENDING_BASELINE_PURPOSE,
                source=PENDING_BASELINE_SOURCE,
                scope_kind="workflow",
                scope_id=workflow_id,
                created_at=created_at,
                expires_at=expires_at,
            )
            if result.recorded_path:
                snapshot_count += 1
        session.commit()

    if snapshot_count:
        logger.add_sink("validation").info(
            "pending_files_snapshots_recorded",
            data={
                "event": "pending_files_snapshots_recorded",
                "workflow_id": workflow_id,
                "snapshot_count": snapshot_count,
            },
        )
    return snapshot_count


def _pending_diff_metadata(
    item: RetrievedItem,
    *,
    workflow_id: str,
    vault_path: str,
) -> dict[str, Any]:
    try:
        vault_root = Path(vault_path).resolve()
        current_path = Path(_resolve_item_path(item, vault_path=vault_path)).resolve()
        relative_path = _vault_relative_path(current_path, vault_root=vault_root)
        baseline = _latest_pending_baseline(
            workflow_id=workflow_id,
            vault_id=resolve_or_create_vault_identity(vault_root).vault_id,
            path=relative_path,
        )
        if baseline is None:
            return _diff_unavailable(
                path=relative_path,
                reason="processed_baseline_unavailable",
            )
        file_snapshot, snapshot_set = baseline
        if not file_snapshot.snapshot_ref:
            return _diff_unavailable(
                path=relative_path,
                reason="processed_baseline_unavailable",
            )
        baseline_path = Path(snapshot_set.snapshot_root) / file_snapshot.snapshot_ref
        if not baseline_path.is_file() or not current_path.is_file():
            return _diff_unavailable(
                path=relative_path,
                reason="processed_baseline_unavailable",
                file_snapshot_id=file_snapshot.id,
                snapshot_set_id=snapshot_set.id,
            )
        baseline_text = baseline_path.read_text(encoding="utf-8")
        current_text = current_path.read_text(encoding="utf-8")
        current_hash = hash_file_bytes(current_path, length=None)
        diff_text = "".join(
            difflib.unified_diff(
                baseline_text.splitlines(keepends=True),
                current_text.splitlines(keepends=True),
                fromfile=f"{relative_path} (last processed)",
                tofile=f"{relative_path} (current)",
            )
        )
        return {
            "available": True,
            "format": "unified",
            "path": relative_path,
            "has_changes": bool(diff_text),
            "text": diff_text,
            "baseline_processed_at": _isoformat(file_snapshot.created_at),
            "baseline_hash": file_snapshot.content_hash,
            "current_hash": current_hash,
            "snapshot_set_id": snapshot_set.id,
            "file_snapshot_id": file_snapshot.id,
        }
    except UnicodeDecodeError:
        return _diff_unavailable(
            path=_safe_item_path(item),
            reason="text_diff_unavailable",
        )
    except Exception as exc:  # noqa: BLE001
        return _diff_unavailable(
            path=_safe_item_path(item),
            reason=type(exc).__name__,
        )


def _latest_pending_baseline(
    *,
    workflow_id: str,
    vault_id: str,
    path: str,
) -> tuple[FileSnapshot, SnapshotSet] | None:
    service = VaultStateService()
    with service.SessionFactory() as session:
        row = session.execute(
            select(FileSnapshot, SnapshotSet)
            .join(SnapshotSet, FileSnapshot.snapshot_set_id == SnapshotSet.id)
            .where(
                FileSnapshot.vault_id == vault_id,
                FileSnapshot.path == path,
                FileSnapshot.source == PENDING_BASELINE_SOURCE,
                FileSnapshot.exists.is_(True),
                SnapshotSet.purpose == PENDING_BASELINE_PURPOSE,
                SnapshotSet.scope_id == workflow_id,
            )
            .order_by(FileSnapshot.created_at.desc(), FileSnapshot.id.desc())
        ).first()
        if row is None:
            return None
        file_snapshot, snapshot_set = row
        return file_snapshot, snapshot_set


def _diff_unavailable(
    *,
    path: str,
    reason: str,
    file_snapshot_id: int | None = None,
    snapshot_set_id: int | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "available": False,
        "path": path,
        "reason": reason,
    }
    if file_snapshot_id is not None:
        metadata["file_snapshot_id"] = file_snapshot_id
    if snapshot_set_id is not None:
        metadata["snapshot_set_id"] = snapshot_set_id
    return metadata


def _resolve_item_path(item: RetrievedItem, *, vault_path: str) -> str:
    source_path = _source_path_from_item(item)
    if os.path.isabs(source_path):
        return source_path
    return os.path.join(vault_path, source_path)


def _vault_relative_path(path: Path, *, vault_root: Path) -> str:
    relative = path.resolve().relative_to(vault_root.resolve())
    return normalize_vault_relative_path(relative)


def _safe_item_path(item: RetrievedItem) -> str:
    try:
        return _source_path_from_item(item)
    except Exception:  # noqa: BLE001
        return str(item.ref or "")


def _isoformat(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None


def _source_path_from_item(item: RetrievedItem) -> str:
    metadata = dict(item.metadata or {})
    source_path = str(metadata.get("source_path") or item.ref or "").strip()
    if not source_path:
        raise ValueError("pending_files items must include source_path metadata or a file ref")
    return source_path


def _contract() -> dict[str, object]:
    return {
        "signature": (
            "pending_files(*, operation: str, items: ScriptToolResult | RetrievedItem | list[RetrievedItem] | tuple[RetrievedItem, ...])"
        ),
        "summary": (
            "Filter or complete workflow pending files. "
            "Use `get` to filter a file_ops_safe result set down to the unprocessed subset and "
            "`complete` to mark a selected subset as processed."
        ),
        "arguments": {
            "operation": {
                "type": "string",
                "required": True,
                "description": "Operation name. Supported values: get, complete.",
            },
            "items": {
                "type": "ScriptToolResult | RetrievedItem | list | tuple",
                "required": True,
                "description": "A file_ops_safe result set or explicit pending file items to filter or complete.",
            },
        },
        "return_shape": {
            "operation": "Resolved operation name.",
            "status": "High-level result status.",
            "items": "Pending subset for get operations. Each item includes metadata.pending_diff when diff metadata can be resolved.",
            "completed_count": "Number of files marked processed for complete operations.",
        },
        "examples": [
            {
                "code": (
                    'listed = await file_ops_safe(operation="list", path="tasks")\n'
                    'pending = await pending_files(operation="get", items=listed)\n'
                    "selected = pending.items[:3]\n"
                    "# ...process selected...\n"
                    'await pending_files(operation="complete", items=selected)'
                ),
                "description": "Filter a candidate file set to unprocessed items, then mark the processed subset complete.",
            }
        ],
    }
