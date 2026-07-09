"""Read-only vault file operations tool."""

from __future__ import annotations

from typing import Any

from pydantic_ai.messages import ToolReturn
from pydantic_ai.tools import Tool

from core.logger import UnifiedLogger
from core.vault_state.file_operations import (
    VaultFileOperationRejected,
    VaultFileOperationResult,
    list_vault_paths_operation,
    read_vault_file_operation,
    search_vault_files_operation,
)

from .base import BaseTool


logger = UnifiedLogger(tag="file-read-tool")


class FileRead(BaseTool):
    """Read, list, and search vault files."""

    @classmethod
    def get_tool(cls, vault_path: str | None = None) -> Tool:
        """Return the Pydantic AI tool for read-only vault operations."""

        def file_read(
            *,
            operation: str,
            path: str = "",
            recursive: bool = False,
            search_term: str = "",
            start_line: int = 0,
            line_count: int = 0,
        ) -> ToolReturn:
            """Read, list, or search vault files.

            :param operation: One of read, list, search.
            :param path: Vault-relative file or directory path.
            :param recursive: Recurse through subdirectories for list.
            :param search_term: Text to search for.
            :param start_line: Optional 1-indexed first line for read.
            :param line_count: Optional number of lines for read.
            """
            try:
                logger.set_sinks(["validation"]).info(
                    "tool_invoked",
                    data={
                        "tool": "file_read",
                        "operation": operation,
                        "vault": vault_path.rstrip("/").split("/")[-1] if vault_path else None,
                    },
                )
                if not vault_path:
                    raise ValueError("vault_path is required for file operations")
                normalized = operation.strip().lower()
                if normalized == "read":
                    return _to_tool_return(
                        read_vault_file_operation(
                            vault_path=vault_path,
                            path=path,
                            start_line=start_line,
                            line_count=line_count,
                        )
                    )
                if normalized == "list":
                    return _to_tool_return(
                        list_vault_paths_operation(
                            vault_path=vault_path,
                            path=path,
                            recursive=recursive,
                        )
                    )
                if normalized == "search":
                    return _to_tool_return(
                        search_vault_files_operation(
                            vault_path=vault_path,
                            path=path,
                            search_term=search_term,
                        )
                    )
                return _error_result(
                    f"Unknown operation '{operation}'. Available: read, list, search",
                    operation=operation,
                    path=path,
                    error_type="unknown_operation",
                )
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
                    error_type=type(exc).__name__,
                )

        return Tool(
            file_read,
            name="file_read",
            description="Read, list, and search files within the current vault.",
        )

    @classmethod
    def get_instructions(cls) -> str:
        """Return usage instructions for read-only file operations."""
        return """
Full documentation:
- `__virtual_docs__/tools/file_read.md`
"""


def _to_tool_return(result: VaultFileOperationResult) -> ToolReturn:
    metadata = {"tool_name": "file_read", **result.metadata}
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
    error_type: str,
    metadata: dict[str, Any] | None = None,
) -> ToolReturn:
    payload = {
        "tool_name": "file_read",
        "status": "error",
        "operation": operation,
        "error_type": error_type,
    }
    if path:
        payload["path"] = path
    if metadata:
        payload.update(metadata)
    return ToolReturn(return_value=message, metadata=payload)
