"""Shared runtime helpers used by Monty helper executors."""

from __future__ import annotations

import inspect
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.messages import ModelMessage, ToolReturn
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from core.authoring.contracts import ScriptToolResult, ContextMessage, RetrieveResult, RetrievedItem
from core.utils.messages import extract_role_and_text, run_slice
from core.logger import UnifiedLogger
from core.runtime.buffers import BufferStore


logger = UnifiedLogger(tag="authoring-host")


def coerce_output_data(value: Any) -> str:
    if isinstance(value, str):
        return value
    return str(value)


def normalize_output_ref(path: str, *, vault_path: str) -> str:
    if not path or not vault_path:
        return path
    try:
        normalized_vault = os.path.realpath(vault_path)
        normalized_path = os.path.realpath(path)
        if normalized_path.startswith(normalized_vault + os.sep):
            return os.path.relpath(normalized_path, normalized_vault).replace("\\", "/")
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "normalize_output_ref failed; returning raw path",
            data={"path": path, "error": str(exc)},
        )
        return path
    return path


def normalize_file_record(record: dict[str, Any]) -> RetrievedItem:
    if record.get("_workflow_signal") == "skip_step":
        return RetrievedItem(
            ref=None,
            content="",
            exists=False,
            metadata={
                "signal": "skip_step",
                "reason": record.get("reason"),
            },
        )

    source_ref = record.get("source_path") or record.get("filepath") or ""
    exists = bool(record.get("found", True))
    metadata = {
        "filename": record.get("filename"),
        "error": record.get("error"),
        "refs_only": bool(record.get("refs_only")),
        "extension": record.get("extension"),
        "size_bytes": record.get("size_bytes"),
        "char_count": record.get("char_count"),
        "token_estimate": record.get("token_estimate"),
        "mtime_epoch": record.get("mtime_epoch"),
        "ctime_epoch": record.get("ctime_epoch"),
        "mtime": record.get("mtime"),
        "ctime": record.get("ctime"),
        "filename_dt": record.get("filename_dt"),
    }
    if record.get("filepath") is not None:
        metadata["filepath"] = record.get("filepath")
    if record.get("source_path") is not None:
        metadata["source_path"] = record.get("source_path")
    state_metadata = record.get("_state_metadata")
    if isinstance(state_metadata, dict):
        pattern = str(state_metadata.get("pattern") or "").strip()
        if pattern:
            metadata["pending_pattern"] = pattern
    return RetrievedItem(
        ref=source_ref,
        content=record.get("content", ""),
        exists=exists,
        metadata=metadata,
    )


def normalize_cache_record(*, ref: str, record: dict[str, Any] | None) -> RetrievedItem:
    if record is None:
        return RetrievedItem(ref=ref, content="", exists=False, metadata={})
    metadata = dict(record.get("metadata") or {})
    metadata.update(
        {
            "cache_mode": record.get("cache_mode"),
            "ttl_seconds": record.get("ttl_seconds"),
            "origin": record.get("origin"),
            "created_at": record.get("created_at"),
            "last_accessed_at": record.get("last_accessed_at"),
            "expires_at": record.get("expires_at"),
        }
    )
    return RetrievedItem(
        ref=ref,
        content=str(record.get("raw_content") or ""),
        exists=True,
        metadata=metadata,
    )


def parse_history_limit(options: dict[str, Any], *, default: int | str) -> int | str:
    unknown = sorted(set(options) - {"limit"})
    if unknown:
        raise ValueError(f"Unsupported options: {', '.join(unknown)}")
    raw_limit = options.get("limit", default)
    if isinstance(raw_limit, str):
        normalized = raw_limit.strip().lower()
        if normalized == "all":
            return "all"
        if normalized.isdigit():
            parsed = int(normalized)
            if parsed <= 0:
                raise ValueError("limit must be a positive integer or 'all'")
            return parsed
        raise ValueError("limit must be a positive integer or 'all'")
    if isinstance(raw_limit, int):
        if raw_limit <= 0:
            raise ValueError("limit must be a positive integer or 'all'")
        return raw_limit
    raise ValueError("limit must be a positive integer or 'all'")


def normalize_run_messages(
    message_history: list[ModelMessage],
    *,
    limit: int | str,
) -> tuple[RetrievedItem, ...]:
    if limit == "all":
        selected_messages = list(message_history)
    else:
        selected_messages = run_slice(list(message_history), limit)
    return tuple(normalize_run_message(message) for message in selected_messages)


def normalize_run_message(message: ModelMessage) -> RetrievedItem:
    role, content = extract_role_and_text(message)
    run_id = getattr(message, "run_id", None)
    return RetrievedItem(
        ref=run_id or role,
        content=content,
        exists=True,
        metadata={
            "role": role,
            "run_id": run_id,
            "message_type": type(message).__name__,
        },
    )


def normalize_object_sequence(value: Any, *, field_name: str) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(value)
    raise ValueError(f"{field_name} must be a list or tuple when provided")


def normalize_optional_string(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string when provided")
    normalized = value.strip()
    return normalized or None


def normalize_context_message(value: Any, *, default_role: str | None = None) -> ContextMessage:
    if isinstance(value, ContextMessage):
        return value
    if isinstance(value, RetrievedItem):
        role = str(value.metadata.get("role") or default_role or "system").strip().lower()
        return ContextMessage(role=role, content=value.content, metadata=dict(value.metadata))
    if isinstance(value, dict):
        role = str(value.get("role") or default_role or "system").strip().lower()
        content = str(value.get("content") or "")
        metadata = value.get("metadata")
        if metadata is None:
            metadata_dict: dict[str, Any] = {}
        elif isinstance(metadata, dict):
            metadata_dict = dict(metadata)
        else:
            raise ValueError("assemble_context message metadata must be a dictionary when provided")
        return ContextMessage(role=role, content=content, metadata=metadata_dict)
    if isinstance(value, str):
        return ContextMessage(role=(default_role or "system"), content=value)
    raise ValueError(
        "assemble_context messages must be RetrievedItem, ContextMessage, dict, or string values"
    )


async def invoke_bound_tool(
    tool_function: Any,
    *,
    tool_name: str,
    arguments: dict[str, Any],
    run_buffers: BufferStore,
    session_buffers: BufferStore,
    session_id: str | None = None,
    chat_session_id: str | None = None,
    vault_name: str | None = None,
    message_history: list[ModelMessage] | tuple[ModelMessage, ...] | None = None,
) -> Any:
    ctx = RunContext(
        deps=SimpleNamespace(
            buffer_store=run_buffers,
            buffer_store_registry={
                "run": run_buffers,
                "session": session_buffers,
            },
            session_id=session_id or chat_session_id,
            chat_session_id=chat_session_id,
            vault_name=vault_name,
            message_history=list(message_history or ()),
        ),
        model=TestModel(),
        usage=RunUsage(),
        tool_name=tool_name,
    )
    result = tool_function.function(ctx, **arguments)
    if inspect.isawaitable(result):
        return await result
    return result


def normalize_tool_result(
    tool_name: str,
    result: Any,
    *,
    vault_path: str = "",
) -> ScriptToolResult:
    if isinstance(result, ToolReturn):
        metadata = dict(result.metadata) if isinstance(result.metadata, dict) else {}
        metadata["return_type"] = "tool_return"
        metadata["has_content"] = result.content is not None
        output = coerce_output_data(result.return_value)
        content = result.content
        return ScriptToolResult(
            name=tool_name,
            status=str(metadata.get("status") or "completed"),
            output=output,
            metadata=metadata,
            content=content,
            items=_project_tool_items(
                tool_name=tool_name,
                output=output,
                metadata=metadata,
                content=content,
                vault_path=vault_path,
            ),
        )
    if isinstance(result, (dict, list, tuple)):
        try:
            output = json.dumps(result, ensure_ascii=False, indent=2)
            metadata = {"return_type": "json"}
            return ScriptToolResult(
                name=tool_name,
                status="completed",
                output=output,
                metadata=metadata,
                items=_project_tool_items(
                    tool_name=tool_name,
                    output=output,
                    metadata=metadata,
                    content=None,
                    vault_path=vault_path,
                ),
            )
        except (TypeError, ValueError):
            pass
    output = coerce_output_data(result)
    metadata = {"return_type": "text"}
    return ScriptToolResult(
        name=tool_name,
        status="completed",
        output=output,
        metadata=metadata,
        items=_project_tool_items(
            tool_name=tool_name,
            output=output,
            metadata=metadata,
            content=None,
            vault_path=vault_path,
        ),
    )


def _project_tool_items(
    *,
    tool_name: str,
    output: str,
    metadata: dict[str, Any],
    content: Any | None,
    vault_path: str,
) -> tuple[RetrievedItem, ...]:
    if tool_name == "file_ops_safe":
        return _project_file_ops_safe_items(
            output=output,
            metadata=metadata,
            content=content,
            vault_path=vault_path,
        )
    if tool_name in {
        "browser",
        "web_search_duckduckgo",
        "web_search_tavily",
        "tavily_extract",
        "tavily_crawl",
        "internal_api",
    } and output.strip():
        return (
            RetrievedItem(
                ref=str(metadata.get("url") or metadata.get("endpoint") or tool_name),
                content=output,
                exists=True,
                metadata={"source_tool": tool_name, **metadata},
            ),
        )
    return ()


def _project_file_ops_safe_items(
    *,
    output: str,
    metadata: dict[str, Any],
    content: Any | None,
    vault_path: str,
) -> tuple[RetrievedItem, ...]:
    status = str(metadata.get("status") or "").strip().lower()
    operation = str(metadata.get("operation") or "").strip().lower()
    if status != "completed":
        return ()

    if operation == "read":
        path = _file_ops_path(metadata)
        if not path:
            return ()
        media_type = str(metadata.get("media_type") or "").strip()
        media_mode = str(metadata.get("media_mode") or "").strip()
        item_metadata = {
            **metadata,
            "source_tool": "file_ops_safe",
            "source_path": path,
            "filepath": str(metadata.get("filepath") or path),
        }
        if media_type.startswith("image/") or media_mode == "image":
            return (
                RetrievedItem(
                    ref=path,
                    content="",
                    exists=True,
                    metadata=item_metadata,
                ),
            )
        return (
            RetrievedItem(
                ref=path,
                content=_file_ops_read_content(
                    path=path,
                    output=output,
                    content=content,
                    vault_path=vault_path,
                ),
                exists=True,
                metadata=item_metadata,
            ),
        )

    if operation in {"list", "search", "frontmatter", "head"}:
        return tuple(
            RetrievedItem(
                ref=path,
                content="",
                exists=True,
                metadata={
                    "source_tool": "file_ops_safe",
                    "source_path": path,
                    "filepath": path,
                    **metadata,
                },
            )
            for path in _file_ops_paths(metadata=metadata, output=output)
        )

    return ()


def _file_ops_path(metadata: dict[str, Any]) -> str:
    for key in ("source_path", "filepath", "path"):
        value = str(metadata.get(key) or "").strip()
        if value:
            return value
    return ""


def _file_ops_paths(*, metadata: dict[str, Any], output: str) -> tuple[str, ...]:
    files = metadata.get("files")
    if isinstance(files, list):
        values = tuple(str(item).strip() for item in files if str(item).strip())
        if values:
            return values

    items = metadata.get("items")
    if isinstance(items, list):
        paths: list[str] = []
        for item in items:
            if isinstance(item, dict):
                candidate = str(item.get("path") or item.get("filepath") or "").strip()
                if candidate:
                    paths.append(candidate)
        if paths:
            return tuple(paths)

    matches = metadata.get("matches")
    if isinstance(matches, list):
        paths = []
        for item in matches:
            candidate = str(item).split(":", 1)[0].strip()
            if candidate:
                paths.append(candidate)
        if paths:
            return tuple(dict.fromkeys(paths))

    parsed: list[str] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line.startswith("📄 "):
            candidate = line.partition(" ")[2].strip()
        elif ":" in line and not line.startswith(("Found ", "No matches", "Search error")):
            candidate = line.split(":", 1)[0].strip()
        else:
            continue
        if candidate:
            parsed.append(candidate)
    return tuple(dict.fromkeys(parsed))


def _file_ops_read_content(
    *,
    path: str,
    output: str,
    content: Any | None,
    vault_path: str,
) -> str:
    if isinstance(content, str):
        return content
    if vault_path:
        try:
            candidate = Path(path)
            full_path = candidate if candidate.is_absolute() else Path(vault_path) / candidate
            resolved_vault = Path(vault_path).resolve()
            resolved_path = full_path.resolve()
            if (
                resolved_path == resolved_vault
                or resolved_vault in resolved_path.parents
            ) and resolved_path.is_file():
                return resolved_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError, ValueError):
            pass
    if "\n\n" in output:
        return output.split("\n\n", 1)[1]
    return output


def normalize_retrieved_items_input(
    value: Any,
    *,
    field_name: str,
) -> tuple[RetrievedItem, ...]:
    if isinstance(value, RetrieveResult):
        return tuple(value.items)
    if isinstance(value, RetrievedItem):
        return (value,)
    if isinstance(value, (list, tuple)):
        normalized: list[RetrievedItem] = []
        for item in value:
            if not isinstance(item, RetrievedItem):
                raise ValueError(
                    f"{field_name} must contain RetrievedItem values or a RetrieveResult"
                )
            normalized.append(item)
        return tuple(normalized)
    raise ValueError(
        f"{field_name} must be a RetrieveResult, RetrievedItem, list, or tuple"
    )
