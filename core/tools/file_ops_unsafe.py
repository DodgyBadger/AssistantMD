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
from core.vault_state.file_mutations import (
    VaultMutationRejected,
    delete_empty_vault_directory_tree,
    delete_vault_file,
    move_vault_file,
    replace_vault_file_content,
)
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
                    return cls._delete_path(path, confirm_path, vault_path)
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
                "Modify, overwrite, truncate, move-overwrite, or delete vault files and empty directories when destructive changes are explicitly needed. "
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

        mutation = replace_vault_file_content(
            vault_path=vault_path,
            path=path,
            content="".join(lines),
            operation="edit_line",
        )

        return cls._result(
            message=f"Successfully edited line {line_number} in '{path}'",
            operation="edit_line",
            path=path,
            status="completed",
            exists=True,
            metadata={
                "line_number": line_number,
                "task_id": mutation.task_id,
                "vault_id": mutation.vault_id,
            },
        )

    @classmethod
    def _delete_path(cls, path: str, confirm_path: str, vault_path: str) -> ToolReturn:
        """Delete a file or clean up empty directories with path confirmation."""
        if path != confirm_path:
            return cls._result(
                message=f"Path confirmation failed - path '{path}' does not match confirm_path '{confirm_path}'",
                operation="delete",
                path=path,
                status="error",
                error_type="confirmation_failed",
            )

        full_path = validate_and_resolve_path(path, vault_path, markdown_only=False)

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
            return cls._delete_empty_directory_tree(path, vault_path)

        try:
            mutation = delete_vault_file(
                vault_path=vault_path,
                path=path,
            )
        except VaultMutationRejected as exc:
            if exc.code != "file_not_found":
                raise
            return cls._result(
                message=f"Cannot delete '{path}' - file does not exist",
                operation="delete",
                path=path,
                status="not_found",
                exists=False,
                error_type="file_not_found",
            )

        return cls._result(
            message=f"⚠️ Successfully deleted '{path}' - this action cannot be undone",
            operation="delete",
            path=path,
            status="completed",
            exists=False,
            metadata={
                "target_type": "file",
                "task_id": mutation.task_id,
                "vault_id": mutation.vault_id,
            },
        )

    @classmethod
    def _delete_empty_directory_tree(cls, path: str, vault_path: str) -> ToolReturn:
        """Best-effort cleanup of empty directories under the confirmed path."""
        try:
            cleanup = delete_empty_vault_directory_tree(
                vault_path=vault_path,
                path=path,
            )
        except VaultMutationRejected as exc:
            if exc.code not in {"directory_not_found", "invalid_target", "not_directory"}:
                raise
            return cls._result(
                message=str(exc),
                operation="delete",
                path=path,
                status="invalid_target" if exc.code != "directory_not_found" else "not_found",
                exists=exc.code != "directory_not_found",
                error_type=exc.code,
            )

        skipped = list(cleanup.skipped_paths)
        removed = list(cleanup.removed_paths)
        blockers = list(cleanup.blocker_paths)
        if skipped:
            blocker_message = ""
            if blockers:
                blocker_message = ". Remaining contents: " + ", ".join(blockers)
            message = (
                f"Removed {len(removed)} empty director"
                f"{'y' if len(removed) == 1 else 'ies'} under '{path}'. "
                f"Skipped {len(skipped)} non-empty director"
                f"{'y' if len(skipped) == 1 else 'ies'}: "
                + ", ".join(skipped)
                + blocker_message
            )
            status = "partial"
        elif removed:
            message = (
                f"⚠️ Removed {len(removed)} empty director"
                f"{'y' if len(removed) == 1 else 'ies'} under '{path}'"
            )
            status = "completed"
        else:
            message = f"No empty directories were removed under '{path}'"
            status = "partial"

        return cls._result(
            message=message,
            operation="delete",
            path=path,
            status=status,
            exists=cleanup.after_exists,
            metadata={
                "target_type": "directory",
                "removed_directories": removed,
                "skipped_non_empty_directories": skipped,
                "remaining_directory_contents": blockers,
                "removed_count": len(removed),
                "skipped_count": len(skipped),
                "remaining_content_count": len(blockers),
                "task_id": cleanup.task_id,
                "vault_id": cleanup.vault_id,
                "event_sequence": cleanup.event_sequence,
            },
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

        mutation = replace_vault_file_content(
            vault_path=vault_path,
            path=path,
            content=new_content,
            operation="replace_text",
        )

        return cls._result(
            message=f"Successfully replaced {replacements} occurrence(s) in '{path}'",
            operation="replace_text",
            path=path,
            status="completed",
            exists=True,
            metadata={
                "replacement_count": replacements,
                "task_id": mutation.task_id,
                "vault_id": mutation.vault_id,
            },
        )

    @classmethod
    def _move_overwrite(cls, path: str, destination: str, vault_path: str) -> ToolReturn:
        """Move file, allowing destination overwrite."""
        src_path = validate_and_resolve_path(path, vault_path, markdown_only=False)
        dest_path = validate_and_resolve_path(destination, vault_path, markdown_only=False)

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

        overwrote_destination = os.path.exists(dest_path)
        try:
            source_mutation, destination_mutation = move_vault_file(
                vault_path=vault_path,
                path=path,
                destination=destination,
                overwrite=True,
            )
        except VaultMutationRejected as exc:
            if exc.code != "source_not_found":
                raise
            return cls._result(
                message=f"Cannot move '{path}' - source file does not exist",
                operation="move_overwrite",
                path=path,
                destination=destination,
                status="not_found",
                exists=False,
                error_type="source_not_found",
            )

        overwrite_msg = " (⚠️ overwrote existing file)" if overwrote_destination else ""

        return cls._result(
            message=f"Successfully moved '{path}' to '{destination}'{overwrite_msg}",
            operation="move_overwrite",
            path=path,
            destination=destination,
            status="completed",
            exists=True,
            metadata={
                "overwrote_destination": bool(overwrite_msg),
                "task_id": source_mutation.task_id or destination_mutation.task_id,
                "vault_id": source_mutation.vault_id,
            },
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

        mutation = replace_vault_file_content(
            vault_path=vault_path,
            path=path,
            content="",
            operation="truncate",
        )

        return cls._result(
            message=f"⚠️ Successfully truncated '{path}' - all contents cleared (this action cannot be undone)",
            operation="truncate",
            path=path,
            status="completed",
            exists=True,
            metadata={
                "task_id": mutation.task_id,
                "vault_id": mutation.vault_id,
            },
        )
