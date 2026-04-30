"""Definition and execution for the pending_files(...) Monty helper."""

from __future__ import annotations

import os
from typing import Any

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
from core.utils.hash import hash_file_bytes, hash_file_content


logger = UnifiedLogger(tag="authoring-host")


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
        host.state_manager.mark_files_processed(file_records)
        logger.add_sink("validation").info(
            "authoring_pending_files_completed",
            data={
                "workflow_id": context.workflow_id,
                "completed_count": len(file_records),
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
        pending_items.append(item)
    return pending_items


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


def _resolve_item_path(item: RetrievedItem, *, vault_path: str) -> str:
    source_path = _source_path_from_item(item)
    if os.path.isabs(source_path):
        return source_path
    return os.path.join(vault_path, source_path)


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
            "items": "Pending subset for get operations.",
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
