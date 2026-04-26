"""
Unsafe / destructive file operations tool.

⚠️ WARNING: This tool can modify and delete existing files. Use with caution.

Provides file editing, deletion, and overwrite capabilities within vault boundaries.
"""

import os
from typing import Any

from pydantic_ai.messages import ToolReturn
from pydantic_ai.tools import Tool

from core.logger import UnifiedLogger
from .base import BaseTool
from .utils import validate_and_resolve_path


logger = UnifiedLogger(tag="file-ops-unsafe-tool")


class FileOpsUnsafe(BaseTool):
    """Unsafe file operations tool with editing and deletion capabilities.

    ⚠️ WARNING: Can permanently modify or delete files.
    """

    @classmethod
    def get_tool(cls, vault_path: str = None):
        """Get the Pydantic AI tool for unsafe file operations.

        :param vault_path: Path to vault for file operations scope
        """

        def file_ops_unsafe(
            *,
            operation: str,
            path: str = "",
            line_number: int = 0,
            old_content: str = "",
            new_content: str = "",
            confirm_path: str = "",
            count: int = 1,
            destination: str = "",
        ) -> str | ToolReturn:
            """Perform unsafe file operations within vault boundaries.

            :param operation: Operation name (edit_line, delete, replace_text, move_overwrite, truncate)
            :param path: File path relative to vault
            :param line_number: Line number for edit_line (1-indexed)
            :param old_content: Expected content for edit_line
            :param new_content: New content for edit_line or replace_text
            :param confirm_path: Path confirmation for delete/truncate
            :param count: Number of replacements for replace_text
            :param destination: Destination path for move_overwrite
            """
            try:
                logger.set_sinks(["validation"]).info(
                    "tool_invoked",
                    data={
                        "tool": "file_ops_unsafe",
                        "vault": vault_path.rstrip("/").split("/")[-1] if vault_path else None,
                    },
                )
                if not vault_path:
                    raise ValueError("vault_path is required for file operations")

                # Route to appropriate helper method
                if operation == "edit_line":
                    return cls._edit_line(path, line_number, old_content, new_content, vault_path)
                elif operation == "delete":
                    return cls._delete_file(path, confirm_path, vault_path)
                elif operation == "replace_text":
                    return cls._replace_text(path, old_content, new_content, count, vault_path)
                elif operation == "move_overwrite":
                    return cls._move_overwrite(path, destination, vault_path)
                elif operation == "truncate":
                    return cls._truncate_file(path, confirm_path, vault_path)
                else:
                    return cls._result(
                        message=(
                            f"Unknown operation '{operation}'. Available: edit_line, delete, replace_text, move_overwrite, truncate"
                        ),
                        operation=operation,
                        path=path,
                        destination=destination,
                        status="error",
                        error_type="unknown_operation",
                    )

            except Exception as e:
                return cls._result(
                    message=f"Error performing '{operation}' operation: {str(e)}",
                    operation=operation,
                    path=path,
                    destination=destination,
                    status="error",
                    error_type=type(e).__name__,
                )

        return Tool(
            file_ops_unsafe,
            name="file_ops_unsafe",
            description=(
                "Modify, overwrite, truncate, move-overwrite, or delete vault files when destructive changes are explicitly needed. "
                "Always confirm with the user before performing a destructive operation with this tool. "
            ),
        )

    @classmethod
    def get_instructions(cls) -> str:
        """Get usage instructions for unsafe file operations."""
        return """
Full documentation:
- `__virtual_docs__/tools/file_ops_unsafe.md`
"""

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

    @classmethod
    def _edit_line(cls, path: str, line_number: int, old_content: str, new_content: str, vault_path: str) -> ToolReturn:
        """Edit a specific line in a file with exact match validation."""
        full_path = validate_and_resolve_path(path, vault_path)

        if not os.path.exists(full_path):
            return cls._result(
                message=f"Cannot edit '{path}' - file does not exist",
                operation="edit_line",
                path=path,
                status="not_found",
                exists=False,
                error_type="file_not_found",
            )

        if line_number < 1:
            return cls._result(
                message=f"Invalid line_number {line_number} - must be >= 1",
                operation="edit_line",
                path=path,
                status="error",
                exists=True,
                error_type="invalid_line_number",
            )

        # Read all lines
        with open(full_path, 'r', encoding='utf-8') as file:
            lines = file.readlines()

        # Validate line number
        if line_number > len(lines):
            return cls._result(
                message=f"Line {line_number} does not exist - file only has {len(lines)} lines",
                operation="edit_line",
                path=path,
                status="invalid_target",
                exists=True,
                error_type="line_not_found",
                metadata={"line_count": len(lines)},
            )

        # Get current line (remove newline for comparison)
        current_line = lines[line_number - 1].rstrip('\n')

        # Validate old_content matches
        if current_line != old_content:
            return cls._result(
                message=(
                    f"Line {line_number} content mismatch. Expected: '{old_content}', Found: '{current_line}'"
                ),
                operation="edit_line",
                path=path,
                status="error",
                exists=True,
                error_type="content_mismatch",
                metadata={"line_number": line_number},
            )

        # Replace the line (handle multi-line new_content)
        if '\n' in new_content:
            # Multi-line replacement
            new_lines = new_content.split('\n')
            lines[line_number - 1:line_number] = [line + '\n' for line in new_lines]
        else:
            # Single line replacement
            lines[line_number - 1] = new_content + '\n'

        # Write back
        with open(full_path, 'w', encoding='utf-8') as file:
            file.writelines(lines)

        return cls._result(
            message=f"Successfully edited line {line_number} in '{path}'",
            operation="edit_line",
            path=path,
            status="completed",
            exists=True,
            metadata={"line_number": line_number},
        )

    @classmethod
    def _delete_file(cls, path: str, confirm_path: str, vault_path: str) -> ToolReturn:
        """Delete a file with path confirmation."""
        if path != confirm_path:
            return cls._result(
                message=f"Path confirmation failed - path '{path}' does not match confirm_path '{confirm_path}'",
                operation="delete",
                path=path,
                status="error",
                error_type="confirmation_failed",
            )

        full_path = validate_and_resolve_path(path, vault_path)

        if not os.path.exists(full_path):
            return cls._result(
                message=f"Cannot delete '{path}' - file does not exist",
                operation="delete",
                path=path,
                status="not_found",
                exists=False,
                error_type="file_not_found",
            )

        if os.path.isdir(full_path):
            return cls._result(
                message=f"Cannot delete '{path}' - this is a directory, not a file",
                operation="delete",
                path=path,
                status="invalid_target",
                exists=True,
                error_type="is_directory",
            )

        os.remove(full_path)
        return cls._result(
            message=f"⚠️ Successfully deleted '{path}' - this action cannot be undone",
            operation="delete",
            path=path,
            status="completed",
            exists=False,
        )

    @classmethod
    def _replace_text(cls, path: str, old_text: str, new_text: str, count: int, vault_path: str) -> ToolReturn:
        """Replace text in file with limited count."""
        full_path = validate_and_resolve_path(path, vault_path)

        if not os.path.exists(full_path):
            return cls._result(
                message=f"Cannot replace text in '{path}' - file does not exist",
                operation="replace_text",
                path=path,
                status="not_found",
                exists=False,
                error_type="file_not_found",
            )

        if count < 1:
            return cls._result(
                message=f"Invalid count {count} - must be >= 1",
                operation="replace_text",
                path=path,
                status="error",
                exists=True,
                error_type="invalid_count",
            )

        # Read file
        with open(full_path, 'r', encoding='utf-8') as file:
            content = file.read()

        # Check if old_text exists
        if old_text not in content:
            return cls._result(
                message=f"Text not found in '{path}': '{old_text}'",
                operation="replace_text",
                path=path,
                status="invalid_target",
                exists=True,
                error_type="text_not_found",
            )

        # Replace with count limit
        new_content = content.replace(old_text, new_text, count)

        # Count actual replacements
        replacements = content.count(old_text) if count >= content.count(old_text) else count

        # Write back
        with open(full_path, 'w', encoding='utf-8') as file:
            file.write(new_content)

        return cls._result(
            message=f"Successfully replaced {replacements} occurrence(s) in '{path}'",
            operation="replace_text",
            path=path,
            status="completed",
            exists=True,
            metadata={"replacement_count": replacements},
        )

    @classmethod
    def _move_overwrite(cls, path: str, destination: str, vault_path: str) -> ToolReturn:
        """Move file, allowing destination overwrite."""
        src_path = validate_and_resolve_path(path, vault_path)
        dest_path = validate_and_resolve_path(destination, vault_path)

        if not os.path.exists(src_path):
            return cls._result(
                message=f"Cannot move '{path}' - source file does not exist",
                operation="move_overwrite",
                path=path,
                destination=destination,
                status="not_found",
                exists=False,
                error_type="source_not_found",
            )

        # Create destination directory if needed
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)

        # Check if destination exists
        overwrite_msg = ""
        if os.path.exists(dest_path):
            overwrite_msg = " (⚠️ overwrote existing file)"

        # Move (overwriting if exists)
        os.replace(src_path, dest_path)

        return cls._result(
            message=f"Successfully moved '{path}' to '{destination}'{overwrite_msg}",
            operation="move_overwrite",
            path=path,
            destination=destination,
            status="completed",
            exists=True,
            metadata={"overwrote_destination": bool(overwrite_msg)},
        )

    @classmethod
    def _truncate_file(cls, path: str, confirm_path: str, vault_path: str) -> ToolReturn:
        """Clear all contents of a file with path confirmation."""
        if path != confirm_path:
            return cls._result(
                message=f"Path confirmation failed - path '{path}' does not match confirm_path '{confirm_path}'",
                operation="truncate",
                path=path,
                status="error",
                error_type="confirmation_failed",
            )

        full_path = validate_and_resolve_path(path, vault_path)

        if not os.path.exists(full_path):
            return cls._result(
                message=f"Cannot truncate '{path}' - file does not exist",
                operation="truncate",
                path=path,
                status="not_found",
                exists=False,
                error_type="file_not_found",
            )

        if os.path.isdir(full_path):
            return cls._result(
                message=f"Cannot truncate '{path}' - this is a directory, not a file",
                operation="truncate",
                path=path,
                status="invalid_target",
                exists=True,
                error_type="is_directory",
            )

        # Clear file contents
        with open(full_path, 'w', encoding='utf-8') as file:
            file.write('')

        return cls._result(
            message=f"⚠️ Successfully truncated '{path}' - all contents cleared (this action cannot be undone)",
            operation="truncate",
            path=path,
            status="completed",
            exists=True,
        )
