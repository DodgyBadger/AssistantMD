"""
File operations tool for chat-driven workflows.

Provides secure file management capabilities within vault boundaries.
"""

import os
import glob
import shutil
import subprocess
from .base import BaseTool
from .utils import validate_and_resolve_path


class FileOpsSafe(BaseTool):
    """Safe file operations tool with vault boundary enforcement."""

    @classmethod
    def get_tool(cls, vault_path: str = None):
        """Get the Pydantic AI tool for file operations.
        
        Args:
            vault_path: Path to vault for file operations scope
        """
        
        def file_operations(operation: str, path: str = "", content: str = "", destination: str = "", pattern: str = "") -> str:
            """Perform file operations within vault boundaries.

            Args:
                operation: Operation to perform (read, write, move, list, mkdir, search)
                path: File or directory path relative to vault (or search pattern for 'search')
                content: Content for write operations
                destination: Destination path for move operations
                pattern: File pattern for list/search operations (e.g., '*.md', '*.py')

            Returns:
                Operation result message
            """
            try:
                if not vault_path:
                    raise ValueError("vault_path is required for file operations")

                # Route to appropriate helper method
                if operation == "read":
                    return cls._read_file(path, vault_path)
                elif operation == "write":
                    return cls._write_file(path, content, vault_path)
                elif operation == "append":
                    return cls._append_file(path, content, vault_path)
                elif operation == "move":
                    return cls._move_file(path, destination, vault_path)
                elif operation == "list":
                    return cls._list_files(path, pattern, vault_path)
                elif operation == "mkdir":
                    return cls._make_directory(path, vault_path)
                elif operation == "search":
                    return cls._search_files(path, pattern, vault_path)
                else:
                    return f"Unknown operation '{operation}'. Available: read, write, append, move, list, mkdir, search"

            except Exception as e:
                return f"Error performing '{operation}' operation: {str(e)}"
        
        return file_operations
    
    @classmethod
    def get_instructions(cls) -> str:
        """Get usage instructions for file operations."""
        return """SAFE file operations within vault boundaries - MARKDOWN FILES ONLY:

DISCOVERY - Start narrow, expand as needed:
- file_operations('list', pattern='*'): List top-level files and directories (START HERE to explore vault structure)
- file_operations('list', pattern='FolderName/*'): List contents of a specific folder (one level)
- file_operations('list', pattern='FolderName/**/*.md'): List all .md files in a folder recursively (use sparingly - can return many files)

SEARCH - Find content within files:
- file_operations('search', path='search-term'): Search for text in all files
- file_operations('search', path='search-term', pattern='*.md'): Search only in markdown files
- file_operations('search', path='TODO', pattern='*.md'): Find all TODO comments in markdown files
- file_operations('search', path='regex-pattern'): Use regex patterns for advanced search
- Results show: filename:line_number:matching_line_content
- Limit: 100 results max to avoid context overflow

⚠️ CONTEXT WINDOW WARNING: Avoid broad searches and recursive lists.
Instead, explore the vault structure first, then target specific folders or file types.

READING & WRITING:
- file_operations('read', 'path/to/file.md'): Read file content
- file_operations('write', 'path/to/file.md', content='text'): Create NEW file (fails if exists)
- file_operations('append', 'path/to/file.md', content='text'): Append to EXISTING file (fails if not exists)
- file_operations('move', 'old/path.md', destination='new/path.md'): Move files (fails if destination exists)
- file_operations('mkdir', 'path/to/directory'): Create directories

BEST PRACTICES:
1. Start exploration with 'list *' to see vault structure
2. Use 'search' to find content across files efficiently
3. Navigate into relevant directories before doing recursive searches
4. Read only files relevant to the user's request
5. All files must use .md extension
6. All operations are SAFE - no overwriting or data loss

"""


    @classmethod
    def _read_file(cls, path: str, vault_path: str) -> str:
        """Read file contents."""
        full_path = validate_and_resolve_path(path, vault_path)

        if os.path.isdir(full_path):
            return f"Cannot read '{path}' - this is a directory, not a file. Use file_operations('list', pattern='{path}/*.md') to see files in this directory."

        if not os.path.exists(full_path):
            return f"Cannot read '{path}' - file does not exist. Use file_operations('list', pattern='*.md') to see available files."

        with open(full_path, 'r', encoding='utf-8') as file:
            file_content = file.read()
        return f"Successfully read file '{path}' ({len(file_content)} characters)\n\n{file_content}"

    @classmethod
    def _write_file(cls, path: str, content: str, vault_path: str) -> str:
        """Write new file (fails if exists)."""
        full_path = validate_and_resolve_path(path, vault_path)

        if os.path.exists(full_path):
            return f"Cannot write to '{path}' - file already exists. Use 'append' operation to add content to existing files."

        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w', encoding='utf-8') as file:
            file.write(content)
        return f"Successfully created new file '{path}' with {len(content)} characters"

    @classmethod
    def _append_file(cls, path: str, content: str, vault_path: str) -> str:
        """Append to existing file."""
        full_path = validate_and_resolve_path(path, vault_path)

        if not os.path.exists(full_path):
            return f"Cannot append to '{path}' - file does not exist. Use 'write' operation to create new files."

        with open(full_path, 'a', encoding='utf-8') as file:
            file.write(content)
        return f"Successfully appended {len(content)} characters to '{path}'"

    @classmethod
    def _move_file(cls, path: str, destination: str, vault_path: str) -> str:
        """Move file to new location."""
        src_path = validate_and_resolve_path(path, vault_path)
        dest_path = validate_and_resolve_path(destination, vault_path)

        if not os.path.exists(src_path):
            return f"Cannot move '{path}' - source file does not exist"

        if os.path.exists(dest_path):
            return f"Cannot move '{path}' to '{destination}' - destination already exists. Choose a different destination path."

        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        shutil.move(src_path, dest_path)
        return f"Successfully moved '{path}' to '{destination}'"

    @classmethod
    def _list_files(cls, path: str, pattern: str, vault_path: str) -> str:
        """List files and directories matching pattern."""
        search_pattern = pattern if pattern else path
        if '..' in search_pattern or search_pattern.startswith('/'):
            raise ValueError("Pattern cannot contain '..' or start with '/'")

        full_pattern = os.path.join(vault_path, search_pattern)
        matches = glob.glob(full_pattern, recursive=True)

        files = []
        directories = []

        for match in matches:
            if match.startswith(vault_path + '/'):
                relative_path = match[len(vault_path) + 1:]
                if os.path.isdir(match):
                    directories.append(relative_path)
                else:
                    files.append(relative_path)

        if not files and not directories:
            return f"No files or directories found matching pattern '{search_pattern}'"

        result_parts = []
        if directories:
            result_parts.append(f"Directories ({len(directories)}):\n" + '\n'.join(f"  📁 {d}/" for d in sorted(directories)))
        if files:
            result_parts.append(f"Files ({len(files)}):\n" + '\n'.join(f"  📄 {f}" for f in sorted(files)))

        return '\n\n'.join(result_parts)

    @classmethod
    def _make_directory(cls, path: str, vault_path: str) -> str:
        """Create directory."""
        full_path = validate_and_resolve_path(path, vault_path)
        os.makedirs(full_path, exist_ok=True)
        return f"Successfully created directory '{path}'"

    @classmethod
    def _search_files(cls, path: str, pattern: str, vault_path: str) -> str:
        """Search for text within files using ripgrep."""
        if not path:
            return "Search requires a search pattern in 'path' parameter"

        # Build ripgrep command
        rg_cmd = ['rg', '--no-heading', '--line-number', '--color', 'never']

        # Add file pattern filter if specified
        if pattern:
            rg_cmd.extend(['--glob', pattern])

        # Add search pattern
        rg_cmd.append(path)

        # Search in vault directory
        rg_cmd.append(vault_path)

        try:
            result = subprocess.run(
                rg_cmd,
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                # Parse output and make it readable
                lines = result.stdout.strip().split('\n')
                if len(lines) > 100:
                    return f"Found {len(lines)} matches (showing first 100):\n\n" + '\n'.join(lines[:100]) + f"\n\n... {len(lines) - 100} more matches truncated"
                return f"Found {len(lines)} matches:\n\n{result.stdout}"
            elif result.returncode == 1:
                # No matches found
                pattern_info = f" in files matching '{pattern}'" if pattern else ""
                return f"No matches found for '{path}'{pattern_info}"
            else:
                # Error occurred
                return f"Search error: {result.stderr or 'Unknown error'}"
        except FileNotFoundError:
            return "Error: ripgrep (rg) not found. Please install ripgrep to use search functionality."
        except subprocess.TimeoutExpired:
            return "Search timed out (>10 seconds). Try narrowing your search with a file pattern."
        except Exception as e:
            return f"Search error: {str(e)}"
