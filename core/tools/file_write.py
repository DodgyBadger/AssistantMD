"""Mutating vault file operations tool."""

from __future__ import annotations

from typing import Any

from pydantic_ai.messages import ToolReturn
from pydantic_ai.tools import Tool

from core.logger import UnifiedLogger
from core.vault_state.file_operations import (
    VaultFileOperationRejected,
    VaultFileOperationResult,
    append_vault_file_operation,
    delete_vault_path_operation,
    edit_vault_line_operation,
    make_vault_directory_operation,
    move_vault_path_operation,
    replace_text_vault_file_operation,
    write_vault_file_operation,
)

from .base import BaseTool


logger = UnifiedLogger(tag="file-write-tool")

_WRITE_OPERATIONS = {
    "write",
    "append",
    "edit_line",
    "replace_text",
    "move",
    "delete",
    "mkdir",
}


class FileWrite(BaseTool):
    """Create, edit, move, delete, and batch mutate vault files."""

    @classmethod
    def get_tool(cls, vault_path: str | None = None) -> Tool:
        """Return the Pydantic AI tool for mutating vault operations."""

        def file_write(
            *,
            operation: str,
            path: str = "",
            content: str = "",
            destination: str = "",
            old_text: str = "",
            new_text: str = "",
            line_number: int = 0,
            count: int = 1,
            overwrite: bool = False,
            confirm_path: str = "",
            operations: list[dict[str, Any]] | None = None,
        ) -> ToolReturn:
            """Create, edit, move, delete, or batch mutate vault files.

            :param operation: One of write, append, edit_line, replace_text, move, delete, mkdir, batch.
            :param path: Vault-relative file or directory path.
            :param content: Full content for write, or content to append.
            :param destination: Destination path for move.
            :param old_text: Exact text to replace for replace_text.
            :param new_text: Replacement text for replace_text.
            :param line_number: One-indexed target line for edit_line.
            :param count: Replacement count for replace_text.
            :param overwrite: For write or move, replace an existing target when true.
            :param confirm_path: Required path confirmation for delete.
            :param operations: Write operation objects for batch.
            """
            try:
                logger.set_sinks(["validation"]).info(
                    "tool_invoked",
                    data={
                        "tool": "file_write",
                        "operation": operation,
                        "vault": vault_path.rstrip("/").split("/")[-1] if vault_path else None,
                    },
                )
                if not vault_path:
                    raise ValueError("vault_path is required for file operations")
                result = _execute_write_operation(
                    vault_path=vault_path,
                    operation=operation,
                    path=path,
                    content=content,
                    destination=destination,
                    old_text=old_text,
                    new_text=new_text,
                    line_number=line_number,
                    count=count,
                    overwrite=overwrite,
                    confirm_path=confirm_path,
                    operations=operations,
                )
                return _to_tool_return(result)
            except VaultFileOperationRejected as exc:
                return _error_result(
                    str(exc),
                    operation=operation,
                    path=str(exc.details.get("path") or path),
                    error_type=exc.code,
                    metadata=exc.details,
                )
            except Exception as exc:
                return _error_result(
                    f"Error performing '{operation}' operation: {exc}",
                    operation=operation,
                    path=path,
                    destination=destination,
                    error_type=type(exc).__name__,
                )

        return Tool(
            file_write,
            name="file_write",
            description=(
                "Create, append, edit lines, replace text, move, delete, create folders, "
                "and batch mutate files within the current vault."
            ),
        )

    @classmethod
    def get_instructions(cls) -> str:
        """Return usage instructions for mutating file operations."""
        return """
Full documentation:
- `__virtual_docs__/tools/file_write.md`
"""


def _execute_write_operation(
    *,
    vault_path: str,
    operation: str,
    path: str,
    content: str,
    destination: str,
    old_text: str,
    new_text: str,
    line_number: int,
    count: int,
    overwrite: bool,
    confirm_path: str,
    operations: list[dict[str, Any]] | None,
) -> VaultFileOperationResult:
    normalized = operation.strip().lower()
    if normalized == "write":
        return write_vault_file_operation(
            vault_path=vault_path,
            path=path,
            content=content,
            overwrite=overwrite,
        )
    if normalized == "append":
        return append_vault_file_operation(vault_path=vault_path, path=path, content=content)
    if normalized == "edit_line":
        return edit_vault_line_operation(
            vault_path=vault_path,
            path=path,
            line_number=line_number,
            old_text=old_text,
            new_text=new_text,
        )
    if normalized == "replace_text":
        return replace_text_vault_file_operation(
            vault_path=vault_path,
            path=path,
            old_text=old_text,
            new_text=new_text,
            count=count,
        )
    if normalized == "move":
        return move_vault_path_operation(
            vault_path=vault_path,
            path=path,
            destination=destination,
            overwrite=overwrite,
        )
    if normalized == "delete":
        return delete_vault_path_operation(
            vault_path=vault_path,
            path=path,
            confirm_path=confirm_path,
        )
    if normalized == "mkdir":
        return make_vault_directory_operation(vault_path=vault_path, path=path)
    if normalized == "batch":
        return _run_batch(vault_path=vault_path, operations=operations or [])
    return VaultFileOperationResult(
        return_value=(
            f"Unknown operation '{operation}'. Available: write, append, edit_line, "
            "replace_text, move, delete, mkdir, batch"
        ),
        metadata={
            "status": "error",
            "operation": operation,
            "path": path,
            "destination": destination,
            "error_type": "unknown_operation",
        },
    )


def _run_batch(
    *,
    vault_path: str,
    operations: list[dict[str, Any]],
) -> VaultFileOperationResult:
    if not operations:
        return VaultFileOperationResult(
            return_value="Batch requires at least one operation.",
            metadata={
                "status": "error",
                "operation": "batch",
                "error_type": "invalid_arguments",
            },
        )
    invalid_rows = _invalid_batch_rows(operations)
    if invalid_rows:
        return VaultFileOperationResult(
            return_value="Batch may contain only write operations.",
            metadata={
                "status": "error",
                "operation": "batch",
                "error_type": "invalid_batch_operation",
                "invalid_rows": invalid_rows,
                "total": len(operations),
                "completed": 0,
                "failed": len(operations),
                "results": [],
            },
        )

    rows: list[dict[str, Any]] = []
    for index, item in enumerate(operations):
        result = _execute_write_operation(
            vault_path=vault_path,
            operation=str(item.get("operation", "")),
            path=str(item.get("path", "")),
            content=str(item.get("content", "")),
            destination=str(item.get("destination", "")),
            old_text=str(item.get("old_text", "")),
            new_text=str(item.get("new_text", "")),
            line_number=int(item.get("line_number", 0)),
            count=int(item.get("count", 1)),
            overwrite=bool(item.get("overwrite", False)),
            confirm_path=str(item.get("confirm_path", "")),
            operations=None,
        )
        metadata = dict(result.metadata)
        rows.append(
            {
                "index": index,
                "status": metadata.get("status", "completed"),
                "operation": metadata.get("operation", item.get("operation", "")),
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
    return VaultFileOperationResult(
        return_value=f"Batch {status}: {completed} completed, {failed} failed.",
        metadata={
            "status": status,
            "operation": "batch",
            "total": len(rows),
            "completed": completed,
            "failed": failed,
            "results": rows,
        },
    )


def _invalid_batch_rows(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    invalid: list[dict[str, Any]] = []
    for index, item in enumerate(operations):
        if not isinstance(item, dict):
            invalid.append(
                {
                    "index": index,
                    "operation": "",
                    "error_type": "invalid_arguments",
                }
            )
            continue
        operation = str(item.get("operation", "")).strip().lower()
        if operation not in _WRITE_OPERATIONS:
            invalid.append(
                {
                    "index": index,
                    "operation": operation,
                    "error_type": (
                        "nested_batch" if operation == "batch" else "read_operation_not_allowed"
                    ),
                }
            )
    return invalid


def _to_tool_return(result: VaultFileOperationResult) -> ToolReturn:
    metadata = {"tool_name": "file_write", **result.metadata}
    return ToolReturn(
        return_value=result.return_value,
        content=result.content,
        metadata=metadata,
    )


def _error_result(
    message: str,
    *,
    operation: str,
    path: str = "",
    destination: str = "",
    error_type: str,
    metadata: dict[str, Any] | None = None,
) -> ToolReturn:
    payload = {
        "tool_name": "file_write",
        "status": "error",
        "operation": operation,
        "error_type": error_type,
    }
    if path:
        payload["path"] = path
    if destination:
        payload["destination"] = destination
    if metadata:
        payload.update(metadata)
    return ToolReturn(return_value=message, metadata=payload)
