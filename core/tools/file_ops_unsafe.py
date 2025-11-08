"""
Unsafe / destructive file operations tool.

⚠️ WARNING: This tool can modify and delete existing files. Use with caution.

Provides file editing, deletion, and overwrite capabilities within vault boundaries.
"""

import os
from .base import BaseTool
from .utils import validate_and_resolve_path


class FileOpsUnsafe(BaseTool):
    """Unsafe file operations tool with editing and deletion capabilities.

    ⚠️ WARNING: Can permanently modify or delete files.
    """

    @classmethod
    def get_tool(cls, vault_path: str = None):
        """Get the Pydantic AI tool for unsafe file operations.

        Args:
            vault_path: Path to vault for file operations scope
        """

        def file_ops_unsafe(operation: str, path: str = "", line_number: int = 0, old_content: str = "", new_content: str = "", confirm_path: str = "", count: int = 1, destination: str = "") -> str:
            """Perform UNSAFE file operations within vault boundaries.

            ⚠️ WARNING: These operations can permanently modify or delete files.

            Args:
                operation: Operation to perform (edit_line, delete, replace_text, move_overwrite, truncate)
                path: File path relative to vault
                line_number: Line number for edit_line (1-indexed)
                old_content: Expected content for edit_line (must match exactly)
                new_content: New content for edit_line or replace_text
                confirm_path: Path confirmation for delete/truncate operations (must match path)
                count: Number of replacements for replace_text (default 1)
                destination: Destination path for move_overwrite

            Returns:
                Operation result message
            """
            try:
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
                    return f"Unknown operation '{operation}'. Available: edit_line, delete, replace_text, move_overwrite, truncate"

            except Exception as e:
                return f"Error performing '{operation}' operation: {str(e)}"

        return file_ops_unsafe

    @classmethod
    def get_instructions(cls) -> str:
        """Get usage instructions for unsafe file operations."""
        return """⚠️ UNSAFE file operations - CAN PERMANENTLY MODIFY OR DELETE FILES:

⚠️ CRITICAL REQUIREMENT: This tool does NOT include read operations (read, list, search).
Before performing ANY file operations, you MUST:
1. Check if file_ops_safe is also enabled
2. If NOT enabled, immediately notify the user: "I need file_ops_safe enabled to read and verify files. Please add it: @tools file_ops_safe, file_ops_unsafe"
3. Do NOT proceed with any operations until file_ops_safe is available

**DESTRUCTIVE OPERATIONS - USE WITH EXTREME CAUTION:**

EDIT LINE (modify specific line in file):
- file_ops_unsafe('edit_line', 'path/to/file.md', line_number=5, old_content='expected line', new_content='new line')
- Line numbers are 1-indexed
- old_content must match current line EXACTLY or operation fails
- new_content can contain \\n for multi-line replacements
- Safety: Fails if old_content doesn't match

DELETE FILE (permanently remove file):
- file_ops_unsafe('delete', 'path/to/file.md', confirm_path='path/to/file.md')
- Requires confirm_path to match path exactly
- Safety: Requires explicit path confirmation

REPLACE TEXT (search and replace in file):
- file_ops_unsafe('replace_text', 'path/to/file.md', old_content='find this', new_content='replace with', count=1)
- Replaces up to 'count' occurrences (default 1)
- Safety: Limited replacement count prevents mass changes

MOVE WITH OVERWRITE (move file, overwriting destination):
- file_ops_unsafe('move_overwrite', 'source.md', destination='dest.md')
- Will overwrite destination if it exists
- Safety: Operation name clearly indicates overwrite risk

TRUNCATE (clear all file contents):
- file_ops_unsafe('truncate', 'path/to/file.md', confirm_path='path/to/file.md')
- Empties file completely
- Requires confirm_path to match path exactly
- Safety: Requires explicit path confirmation

⚠️ CRITICAL SAFETY RULES:
1. All files must use .md extension
2. All operations stay within vault boundaries
3. Delete and truncate require path confirmation
4. Edit operations require exact content match
5. NO UNDO - changes are permanent
6. Double-check paths before destructive operations

REQUIRED: When you modify or delete files, always end your response with:

FILES_MODIFIED_OR_DELETED:
- path/to/file1.md (edited)
- path/to/file2.md (deleted)"""

    @classmethod
    def _edit_line(cls, path: str, line_number: int, old_content: str, new_content: str, vault_path: str) -> str:
        """Edit a specific line in a file with exact match validation."""
        full_path = validate_and_resolve_path(path, vault_path)

        if not os.path.exists(full_path):
            return f"Cannot edit '{path}' - file does not exist"

        if line_number < 1:
            return f"Invalid line_number {line_number} - must be >= 1"

        # Read all lines
        with open(full_path, 'r', encoding='utf-8') as file:
            lines = file.readlines()

        # Validate line number
        if line_number > len(lines):
            return f"Line {line_number} does not exist - file only has {len(lines)} lines"

        # Get current line (remove newline for comparison)
        current_line = lines[line_number - 1].rstrip('\n')

        # Validate old_content matches
        if current_line != old_content:
            return f"Line {line_number} content mismatch. Expected: '{old_content}', Found: '{current_line}'"

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

        return f"Successfully edited line {line_number} in '{path}'"

    @classmethod
    def _delete_file(cls, path: str, confirm_path: str, vault_path: str) -> str:
        """Delete a file with path confirmation."""
        if path != confirm_path:
            return f"Path confirmation failed - path '{path}' does not match confirm_path '{confirm_path}'"

        full_path = validate_and_resolve_path(path, vault_path)

        if not os.path.exists(full_path):
            return f"Cannot delete '{path}' - file does not exist"

        if os.path.isdir(full_path):
            return f"Cannot delete '{path}' - this is a directory, not a file"

        os.remove(full_path)
        return f"⚠️ Successfully deleted '{path}' - this action cannot be undone"

    @classmethod
    def _replace_text(cls, path: str, old_text: str, new_text: str, count: int, vault_path: str) -> str:
        """Replace text in file with limited count."""
        full_path = validate_and_resolve_path(path, vault_path)

        if not os.path.exists(full_path):
            return f"Cannot replace text in '{path}' - file does not exist"

        if count < 1:
            return f"Invalid count {count} - must be >= 1"

        # Read file
        with open(full_path, 'r', encoding='utf-8') as file:
            content = file.read()

        # Check if old_text exists
        if old_text not in content:
            return f"Text not found in '{path}': '{old_text}'"

        # Replace with count limit
        new_content = content.replace(old_text, new_text, count)

        # Count actual replacements
        replacements = content.count(old_text) if count >= content.count(old_text) else count

        # Write back
        with open(full_path, 'w', encoding='utf-8') as file:
            file.write(new_content)

        return f"Successfully replaced {replacements} occurrence(s) in '{path}'"

    @classmethod
    def _move_overwrite(cls, path: str, destination: str, vault_path: str) -> str:
        """Move file, allowing destination overwrite."""
        src_path = validate_and_resolve_path(path, vault_path)
        dest_path = validate_and_resolve_path(destination, vault_path)

        if not os.path.exists(src_path):
            return f"Cannot move '{path}' - source file does not exist"

        # Create destination directory if needed
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)

        # Check if destination exists
        overwrite_msg = ""
        if os.path.exists(dest_path):
            overwrite_msg = " (⚠️ overwrote existing file)"

        # Move (overwriting if exists)
        os.replace(src_path, dest_path)

        return f"Successfully moved '{path}' to '{destination}'{overwrite_msg}"

    @classmethod
    def _truncate_file(cls, path: str, confirm_path: str, vault_path: str) -> str:
        """Clear all contents of a file with path confirmation."""
        if path != confirm_path:
            return f"Path confirmation failed - path '{path}' does not match confirm_path '{confirm_path}'"

        full_path = validate_and_resolve_path(path, vault_path)

        if not os.path.exists(full_path):
            return f"Cannot truncate '{path}' - file does not exist"

        if os.path.isdir(full_path):
            return f"Cannot truncate '{path}' - this is a directory, not a file"

        # Clear file contents
        with open(full_path, 'w', encoding='utf-8') as file:
            file.write('')

        return f"⚠️ Successfully truncated '{path}' - all contents cleared (this action cannot be undone)"
