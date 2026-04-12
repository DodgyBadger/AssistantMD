"""Definition and execution for the pending_files(...) Monty helper."""

from __future__ import annotations

import os
from typing import Any

from core.authoring.contracts import (
    AuthoringCapabilityCall,
    AuthoringCapabilityDefinition,
    AuthoringExecutionContext,
    CallToolResult,
    PendingFilesResult,
    RetrievedItem,
)
from core.authoring.helpers.common import build_capability
from core.logger import UnifiedLogger
from core.utils.hash import hash_file_bytes, hash_file_content


logger = UnifiedLogger(tag="authoring-host")


def build_definition() -> AuthoringCapabilityDefinition:
    return build_capability(
        name="pending_files",
        doc="Filter or complete workflow pending files using an explicit tracking pattern.",
        contract=_contract(),
        handler=execute,
    )


async def execute(
    call: AuthoringCapabilityCall,
    context: AuthoringExecutionContext,
) -> PendingFilesResult:
    host = context.host
    operation, pattern, items = _parse_call(call)
    if not host.state_manager:
        raise ValueError("pending_files requires workflow file-state tracking to be available")
    if operation == "get":
        pending_items = _filter_pending_items(
            items,
            pattern=pattern,
            state_manager=host.state_manager,
            vault_path=host.vault_path or "",
        )
        logger.info(
            "authoring_pending_files_filtered",
            data={
                "workflow_id": context.workflow_id,
                "pattern": pattern,
                "candidate_count": len(items),
                "pending_count": len(pending_items),
            },
        )
        logger.set_sinks(["validation"]).info(
            "authoring_pending_files_filtered",
            data={
                "workflow_id": context.workflow_id,
                "pattern": pattern,
                "candidate_count": len(items),
                "pending_count": len(pending_items),
            },
        )
        return PendingFilesResult(
            operation="get",
            status="completed",
            pattern=pattern,
            items=tuple(pending_items),
        )
    if operation == "complete":
        file_records = _build_completion_records(items, vault_path=host.vault_path or "")
        host.state_manager.mark_files_processed(file_records, pattern)
        logger.info(
            "authoring_pending_files_completed",
            data={
                "workflow_id": context.workflow_id,
                "pattern": pattern,
                "completed_count": len(file_records),
            },
        )
        logger.set_sinks(["validation"]).info(
            "authoring_pending_files_completed",
            data={
                "workflow_id": context.workflow_id,
                "pattern": pattern,
                "completed_count": len(file_records),
            },
        )
        return PendingFilesResult(
            operation="complete",
            status="completed",
            pattern=pattern,
            completed_count=len(file_records),
        )
    raise ValueError("pending_files operation must be one of: get, complete")


def _parse_call(
    call: AuthoringCapabilityCall,
) -> tuple[str, str, tuple[RetrievedItem, ...]]:
    if call.args:
        raise ValueError("pending_files only supports keyword arguments")
    unknown = sorted(set(call.kwargs) - {"operation", "pattern", "items"})
    if unknown:
        raise ValueError(f"Unsupported pending_files arguments: {', '.join(unknown)}")
    operation = str(call.kwargs.get("operation") or "").strip().lower()
    pattern = str(call.kwargs.get("pattern") or "").strip()
    if not operation:
        raise ValueError("pending_files requires a non-empty 'operation'")
    if not pattern:
        raise ValueError("pending_files requires a non-empty 'pattern'")
    if "items" not in call.kwargs:
        raise ValueError("pending_files requires 'items'")
    items = _normalize_pending_items_input(call.kwargs.get("items"))
    return operation, pattern, items


def _normalize_pending_items_input(value: Any) -> tuple[RetrievedItem, ...]:
    if isinstance(value, CallToolResult):
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


def _items_from_tool_result(result: CallToolResult) -> tuple[RetrievedItem, ...]:
    if result.name != "file_ops_safe":
        raise ValueError("pending_files only accepts CallToolResult values from file_ops_safe")
    paths = _extract_paths_from_file_ops_output(result.output)
    return tuple(
        RetrievedItem(
            ref=path,
            content="",
            exists=True,
            metadata={"source_path": path},
        )
        for path in paths
    )


def _extract_paths_from_file_ops_output(output: str) -> tuple[str, ...]:
    paths: list[str] = []
    seen: set[str] = set()
    for raw_line in str(output or "").splitlines():
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
    pattern: str,
    state_manager: Any,
    vault_path: str,
) -> list[RetrievedItem]:
    all_paths = [_resolve_item_path(item, vault_path=vault_path) for item in items]
    pending_paths = {
        os.path.realpath(path)
        for path in state_manager.get_pending_files(all_paths, pattern)
    }
    pending_items: list[RetrievedItem] = []
    for item in items:
        resolved_path = os.path.realpath(_resolve_item_path(item, vault_path=vault_path))
        if resolved_path not in pending_paths:
            continue
        metadata = dict(item.metadata or {})
        metadata["pending_pattern"] = pattern
        pending_items.append(
            RetrievedItem(
                ref=item.ref,
                content=item.content,
                exists=item.exists,
                metadata=metadata,
            )
        )
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
            "pending_files(*, operation: str, pattern: str, items: CallToolResult | RetrievedItem | list[RetrievedItem] | tuple[RetrievedItem, ...])"
        ),
        "summary": (
            "Filter or complete workflow pending files using an explicit tracking pattern. "
            "Use `get` to filter a file_ops_safe result set down to the pending subset and "
            "`complete` to mark a selected subset processed."
        ),
        "arguments": {
            "operation": {
                "type": "string",
                "required": True,
                "description": "Operation name. Supported values: get, complete.",
            },
            "pattern": {
                "type": "string",
                "required": True,
                "description": "Stable pending-tracking key, usually the watched file pattern.",
            },
            "items": {
                "type": "CallToolResult | RetrievedItem | list | tuple",
                "required": True,
                "description": "A file_ops_safe result set or explicit pending file items to filter or complete.",
            },
        },
        "return_shape": {
            "operation": "Resolved operation name.",
            "status": "High-level result status.",
            "pattern": "Pending tracking pattern.",
            "items": "Pending subset for get operations.",
            "completed_count": "Number of files marked processed for complete operations.",
        },
        "examples": [
            {
                "code": (
                    'listed = await call_tool(\n'
                    '    name="file_ops_safe",\n'
                    '    arguments={"operation": "list", "target": "tasks"},\n'
                    ')\n'
                    'pending = await pending_files(operation="get", pattern="tasks/*.md", items=listed)\n'
                    "selected = pending.items[:3]\n"
                    "# ...process selected...\n"
                    'await pending_files(operation="complete", pattern="tasks/*.md", items=selected)'
                ),
                "description": "Filter a watched file set to pending items and then mark only the processed subset complete.",
            }
        ],
    }
