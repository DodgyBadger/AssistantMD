"""Unified vault file operations tool."""

from __future__ import annotations

import os
from typing import Any

from pydantic_ai.messages import ToolReturn
from pydantic_ai.tools import Tool

from core.logger import UnifiedLogger
from core.settings import get_file_ops_safe_list_max_results
from core.vault_state.file_mutations import (
    VaultMutationRejected,
    replace_vault_file_content,
    write_vault_file,
)

from .base import BaseTool
from .file_ops_safe import FileOpsSafe
from .file_ops_unsafe import FileOpsUnsafe
from .utils import get_virtual_mount_key, validate_and_resolve_path


logger = UnifiedLogger(tag="file-ops-tool")


class FileOps(BaseTool):
    """Unified file operations tool with vault boundary enforcement."""

    @classmethod
    def get_tool(cls, vault_path: str | None = None) -> Tool:
        """Return the Pydantic AI tool for unified file operations."""

        def file_ops(
            *,
            operation: str,
            path: str = "",
            content: str = "",
            destination: str = "",
            recursive: bool = False,
            search_term: str = "",
            old_text: str = "",
            new_text: str = "",
            count: int = 1,
            overwrite: bool = False,
            confirm_path: str = "",
            start_line: int = 0,
            line_count: int = 0,
            operations: list[dict[str, Any]] | None = None,
        ) -> str | ToolReturn:
            """Read, search, write, edit, move, or delete vault files.

            :param operation: One of read, list, search, write, append, replace_text, move, delete, mkdir, batch.
            :param path: Vault-relative file or directory path.
            :param content: Full file content for write, or content to append.
            :param destination: Destination path for move.
            :param recursive: Recurse through subdirectories for list.
            :param search_term: Text to search for.
            :param old_text: Exact text to replace for replace_text.
            :param new_text: Replacement text for replace_text.
            :param count: Replacement count for replace_text.
            :param overwrite: For write, replace existing full-file content when true.
            :param confirm_path: Required path confirmation for delete.
            :param start_line: Optional 1-indexed first line for read.
            :param line_count: Optional number of lines for read.
            :param operations: Operation objects for batch.
            """
            try:
                logger.set_sinks(["validation"]).info(
                    "tool_invoked",
                    data={
                        "tool": "file_ops",
                        "operation": operation,
                        "vault": vault_path.rstrip("/").split("/")[-1] if vault_path else None,
                    },
                )
                if not vault_path:
                    raise ValueError("vault_path is required for file operations")

                return cls._execute_operation(
                    operation=operation,
                    path=path,
                    content=content,
                    destination=destination,
                    recursive=recursive,
                    search_term=search_term,
                    old_text=old_text,
                    new_text=new_text,
                    count=count,
                    overwrite=overwrite,
                    confirm_path=confirm_path,
                    start_line=start_line,
                    line_count=line_count,
                    operations=operations,
                    vault_path=vault_path,
                )
            except VaultMutationRejected as exc:
                return cls._result(
                    message=str(exc),
                    operation=operation,
                    path=path,
                    destination=destination,
                    status="error",
                    error_type=exc.code,
                )
            except Exception as exc:
                return cls._result(
                    message=f"Error performing '{operation}' operation: {exc}",
                    operation=operation,
                    path=path,
                    destination=destination,
                    status="error",
                    error_type=type(exc).__name__,
                )

        return Tool(
            file_ops,
            name="file_ops",
            description=(
                "Read, list, search, write, append, replace text, move, delete, "
                "and create folders within the current vault."
            ),
        )

    @classmethod
    def get_instructions(cls) -> str:
        """Return usage instructions for file operations."""
        return """
Full documentation:
- `__virtual_docs__/tools/file_ops.md`
"""

    @classmethod
    def _execute_operation(
        cls,
        *,
        operation: str,
        path: str,
        content: str,
        destination: str,
        recursive: bool,
        search_term: str,
        old_text: str,
        new_text: str,
        count: int,
        overwrite: bool,
        confirm_path: str,
        start_line: int,
        line_count: int,
        operations: list[dict[str, Any]] | None,
        vault_path: str,
    ) -> ToolReturn:
        normalized = operation.strip().lower()
        if normalized == "read":
            result = FileOpsSafe._read_file(path, vault_path)
            if start_line > 0 or line_count > 0:
                return cls._line_slice_read_result(
                    result=result,
                    path=path,
                    start_line=start_line,
                    line_count=line_count,
                )
            return cls._normalize_result(result, operation="read")
        if normalized == "list":
            result = (
                FileOpsSafe._list_virtual_mount(
                    path,
                    recursive=recursive,
                    max_results=get_file_ops_safe_list_max_results(),
                )
                if get_virtual_mount_key(path)
                else FileOpsSafe._list_files(
                    path,
                    vault_path,
                    recursive=recursive,
                    max_results=get_file_ops_safe_list_max_results(),
                )
            )
            return cls._normalize_result(result, operation="list")
        if normalized == "search":
            return cls._normalize_result(
                FileOpsSafe._search_files(path, search_term, vault_path),
                operation="search",
            )
        if normalized == "write":
            result = (
                cls._overwrite_file(path, content, vault_path)
                if overwrite
                else FileOpsSafe._write_file(path, content, vault_path)
            )
            return cls._normalize_result(result, operation="write")
        if normalized == "append":
            return cls._normalize_result(
                FileOpsSafe._append_file(path, content, vault_path),
                operation="append",
            )
        if normalized == "replace_text":
            return cls._normalize_result(
                FileOpsUnsafe._replace_text(path, old_text, new_text, count, vault_path),
                operation="replace_text",
            )
        if normalized == "move":
            return cls._normalize_result(
                FileOpsSafe._move_file(path, destination, vault_path),
                operation="move",
            )
        if normalized == "delete":
            return cls._normalize_result(
                FileOpsUnsafe._delete_path(path, confirm_path, vault_path),
                operation="delete",
            )
        if normalized == "mkdir":
            return cls._normalize_result(
                FileOpsSafe._make_directory(path, vault_path),
                operation="mkdir",
            )
        if normalized == "batch":
            return cls._run_batch(operations or [], vault_path)
        return cls._result(
            message=(
                f"Unknown operation '{operation}'. Available: read, list, search, write, append, "
                "replace_text, move, delete, mkdir, batch"
            ),
            operation=operation,
            path=path,
            destination=destination,
            status="error",
            error_type="unknown_operation",
        )

    @classmethod
    def _run_batch(cls, operations: list[dict[str, Any]], vault_path: str) -> ToolReturn:
        if not operations:
            return cls._result(
                message="Batch requires at least one operation.",
                operation="batch",
                status="error",
                error_type="invalid_arguments",
            )

        rows: list[dict[str, Any]] = []
        for index, item in enumerate(operations):
            if not isinstance(item, dict):
                rows.append(
                    {
                        "index": index,
                        "status": "error",
                        "operation": "",
                        "error_type": "invalid_arguments",
                        "return_value": "Batch operation must be an object.",
                    }
                )
                continue

            row_operation = str(item.get("operation", ""))
            if row_operation.strip().lower() == "batch":
                result = cls._result(
                    message="Nested batch operations are not supported.",
                    operation="batch",
                    status="error",
                    error_type="nested_batch",
                )
            else:
                result = cls._execute_operation(
                    operation=row_operation,
                    path=str(item.get("path", "")),
                    content=str(item.get("content", "")),
                    destination=str(item.get("destination", "")),
                    recursive=bool(item.get("recursive", False)),
                    search_term=str(item.get("search_term", "")),
                    old_text=str(item.get("old_text", "")),
                    new_text=str(item.get("new_text", "")),
                    count=int(item.get("count", 1)),
                    overwrite=bool(item.get("overwrite", False)),
                    confirm_path=str(item.get("confirm_path", "")),
                    start_line=int(item.get("start_line", 0)),
                    line_count=int(item.get("line_count", 0)),
                    operations=None,
                    vault_path=vault_path,
                )
            metadata = dict(result.metadata or {})
            rows.append(
                {
                    "index": index,
                    "status": metadata.get("status", "completed"),
                    "operation": metadata.get("operation", row_operation),
                    "path": metadata.get("path"),
                    "destination": metadata.get("destination"),
                    "error_type": metadata.get("error_type"),
                    "return_value": result.return_value,
                    "metadata": metadata,
                }
            )

        failed = sum(1 for row in rows if row["status"] != "completed")
        completed = len(rows) - failed
        status = "completed" if failed == 0 else "error" if completed == 0 else "partial"
        return cls._result(
            message=f"Batch {status}: {completed} completed, {failed} failed.",
            operation="batch",
            status=status,
            metadata={
                "total": len(rows),
                "completed": completed,
                "failed": failed,
                "results": rows,
            },
        )

    @classmethod
    def _overwrite_file(cls, path: str, content: str, vault_path: str) -> ToolReturn:
        if not path.strip():
            return cls._result(
                message="Path is required for write.",
                operation="write",
                path=path,
                status="error",
                error_type="invalid_path",
            )
        if get_virtual_mount_key(path):
            return cls._result(
                message=f"Cannot write to virtual mount path '{path}'.",
                operation="write",
                path=path,
                status="error",
                error_type="virtual_mount_read_only",
            )
        full_path = validate_and_resolve_path(path, vault_path, markdown_only=True)
        existed_before = os.path.exists(full_path)
        mutation = replace_vault_file_content(
            vault_path=vault_path,
            path=path,
            content=content,
            operation="write",
            markdown_only=True,
        ) if existed_before else write_vault_file(
            vault_path=vault_path,
            path=path,
            content=content,
            fail_if_exists=False,
            markdown_only=True,
        )
        return cls._result(
            message=(
                f"Successfully overwrote '{path}' with {len(content)} characters"
                if existed_before
                else f"Successfully created new file '{path}' with {len(content)} characters"
            ),
            operation="write",
            path=path,
            status="completed",
            exists=True,
            metadata={
                "content_chars": len(content),
                "overwrote": existed_before,
                "task_id": mutation.task_id,
                "vault_id": mutation.vault_id,
            },
        )

    @classmethod
    def _line_slice_read_result(
        cls,
        *,
        result: str | ToolReturn,
        path: str,
        start_line: int,
        line_count: int,
    ) -> ToolReturn:
        normalized = cls._normalize_result(result, operation="read")
        if not isinstance(normalized.return_value, str) or normalized.metadata.get("status") != "completed":
            return normalized
        lines = normalized.return_value.splitlines()
        start = max(start_line, 1) if start_line else 1
        count = line_count if line_count > 0 else len(lines) - start + 1
        selected = lines[start - 1:start - 1 + count]
        metadata = dict(normalized.metadata)
        metadata.update(
            {
                "path": metadata.get("path") or path,
                "start_line": start,
                "line_count": count,
                "lines_returned": len(selected),
                "total_lines": len(lines),
            }
        )
        return ToolReturn(return_value="\n".join(selected), content=normalized.content, metadata=metadata)

    @classmethod
    def _normalize_result(cls, result: str | ToolReturn, *, operation: str) -> ToolReturn:
        if isinstance(result, ToolReturn):
            metadata = dict(result.metadata or {})
            metadata["tool_name"] = "file_ops"
            metadata["operation"] = operation
            return ToolReturn(
                return_value=result.return_value,
                content=result.content,
                metadata=metadata,
            )
        return cls._result(message=str(result), operation=operation)

    @classmethod
    def _result(
        cls,
        *,
        message: str,
        operation: str,
        path: str = "",
        destination: str = "",
        status: str = "completed",
        exists: bool | None = None,
        error_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ToolReturn:
        payload: dict[str, Any] = {
            "tool_name": "file_ops",
            "status": status,
            "operation": operation,
        }
        if path:
            payload["path"] = path
        if destination:
            payload["destination"] = destination
        if exists is not None:
            payload["exists"] = exists
        if error_type:
            payload["error_type"] = error_type
        if metadata:
            payload.update(metadata)
        return ToolReturn(return_value=message, metadata=payload)
