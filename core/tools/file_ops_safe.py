"""
File operations tool for chat-driven workflows.

Provides secure file management capabilities within vault boundaries.
"""

import os
import glob
import shutil
import subprocess
from pydantic_ai.tools import Tool

from core.logger import UnifiedLogger
from .base import BaseTool
from .utils import validate_and_resolve_path


logger = UnifiedLogger(tag="file-ops-safe-tool")


class FileOpsSafe(BaseTool):
    """Safe file operations tool with vault boundary enforcement."""

    @classmethod
    def get_tool(cls, vault_path: str = None):
        """Get the Pydantic AI tool for file operations.
        
        Args:
            vault_path: Path to vault for file operations scope
        """
        
        def file_operations(
            *,
            operation: str,
            target: str = "",
            content: str = "",
            destination: str = "",
            include_all: bool = False,
            recursive: bool = False,
            scope: str = "",
        ) -> str:
            """Perform file operations within vault boundaries.

            Args:
                operation: Operation to perform (read, write, move, list, mkdir, search)
                target: File, directory, or glob pattern relative to vault (search term for 'search')
                content: Content for write operations
                destination: Destination path for move operations
                include_all: When True, include non-markdown and hidden files in listings
                recursive: When True, recurse through subdirectories for listings
                scope: Optional folder or glob to limit search (applies to 'search' only)

            Returns:
                Operation result message
            """
            try:
                logger.set_sinks(["validation"]).info(
                    "tool_invoked",
                    data={
                        "tool": "file_ops_safe",
                        "vault": vault_path.rstrip("/").split("/")[-1] if vault_path else None,
                    },
                )
                if not vault_path:
                    raise ValueError("vault_path is required for file operations")

                # Route to appropriate helper method
                if operation == "read":
                    return cls._read_file(target, vault_path)
                elif operation == "write":
                    return cls._write_file(target, content, vault_path)
                elif operation == "append":
                    return cls._append_file(target, content, vault_path)
                elif operation == "move":
                    return cls._move_file(target, destination, vault_path)
                elif operation == "list":
                    return cls._list_files(target, vault_path, include_all=include_all, recursive=recursive)
                elif operation == "mkdir":
                    return cls._make_directory(target, vault_path)
                elif operation == "search":
                    return cls._search_files(target, scope, vault_path)
                else:
                    return f"Unknown operation '{operation}'. Available: read, write, append, move, list, mkdir, search"

            except Exception as e:
                return f"Error performing '{operation}' operation: {str(e)}"
        
        return Tool(file_operations, name="file_ops_safe")
    
    @classmethod
    def get_instructions(cls) -> str:
        """Get usage instructions for file operations."""
        return """SAFE file operations within vault boundaries - MARKDOWN FILES ONLY:

DISCOVERY - Start narrow, expand as needed:
- file_ops_safe(operation="list"): List top-level directories and .md files (START HERE)
- file_ops_safe(operation="list", target="FolderName"): List .md files inside a folder (non-recursive)
- file_ops_safe(operation="list", target="FolderName", recursive=True): Recursive listing (use sparingly - capped at 200 results)
- file_ops_safe(operation="list", target="FolderName/*", include_all=True): Include non-md/hidden files
- file_ops_safe(operation="list", target="notes/**/*.md", recursive=True): Explicit glob pattern for recursive match

SEARCH - Find content within files:
- file_ops_safe(operation="search", target="search-term"): Search for text in all markdown files
- file_ops_safe(operation="search", target="TODO", scope="projects"): Limit search to a folder (folder path adds an implicit '*.md')
- file_ops_safe(operation="search", target="regex-pattern"): Use regex patterns for advanced search
- file_ops_safe(operation="search", target="TODO", scope="notes/*.md"): Scope using a glob
- Results show: filename:line_number:matching_line_content
- Limit: 100 results max to avoid context overflow

⚠️ CONTEXT WINDOW WARNING: Avoid broad searches and recursive lists.
Instead, explore the vault structure first, then target specific folders or file types.

READING & WRITING:
- file_ops_safe(operation="read", target="path/to/file.md"): Read file content
- file_ops_safe(operation="write", target="path/to/file.md", content="text"): Create NEW file (fails if exists)
- file_ops_safe(operation="append", target="path/to/file.md", content="text"): Append to EXISTING file (fails if not exists)
- file_ops_safe(operation="move", target="old/path.md", destination="new/path.md"): Move files (fails if destination exists)
- file_ops_safe(operation="mkdir", target="path/to/directory"): Create directories

BEST PRACTICES:
1. Start exploration with file_ops_safe(operation="list") to see vault structure
2. Use 'search' to find content across files efficiently
3. Navigate into relevant directories before doing recursive searches
4. Read only files relevant to the user's request
5. All files must use .md extension
6. All operations are SAFE - no overwriting or data loss

NOTE:
- Always use named parameters; positional arguments are not supported.
- You may route output with output="variable:NAME" or output="file:PATH" and optional write_mode=append|replace|new.
- output must be a string (no JSON objects or dicts).
- Example routing: file_ops_safe(operation="read", target="path.md", output="variable:LEASE", write_mode="replace")

"""


    @classmethod
    def _read_file(cls, path: str, vault_path: str) -> str:
        """Read file contents."""
        full_path = validate_and_resolve_path(path, vault_path)

        if os.path.isdir(full_path):
            return f"Cannot read '{path}' - this is a directory, not a file. Use file_operations('list', target='{path}') to see files in this directory."

        if not os.path.exists(full_path):
            return f"Cannot read '{path}' - file does not exist. Use file_operations('list') to see available files."

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
    def _list_files(cls, target: str, vault_path: str, include_all: bool, recursive: bool, max_results: int = 200) -> str:
        """List files and directories matching a target path or glob."""
        # Default to top-level view
        target = target.strip()
        if not target or target == ".":
            target = "*"

        if '..' in target or target.startswith('/'):
            raise ValueError("Target cannot contain '..' or start with '/'")

        # If target points to a directory (no glob), list its immediate contents
        is_glob = any(ch in target for ch in "*?[")
        if not is_glob:
            abs_target = os.path.join(vault_path, target)
            if os.path.isdir(abs_target):
                target = os.path.join(target, "**/*" if recursive else "*")
            else:
                target = target

        full_pattern = os.path.join(vault_path, target)
        matches = glob.glob(full_pattern, recursive=recursive or "**" in target)

        files = []
        directories = []

        for match in matches:
            if not match.startswith(vault_path + os.sep) and match != vault_path:
                continue

            relative_path = match[len(vault_path) + 1:] if match != vault_path else ""

            # Skip hidden paths unless include_all
            parts = relative_path.split(os.sep) if relative_path else []
            if not include_all and any(part.startswith('.') for part in parts if part):
                continue

            if os.path.isdir(match):
                if relative_path:
                    directories.append(relative_path)
                continue

            if not include_all and not relative_path.endswith(".md"):
                continue

            if relative_path:
                files.append(relative_path)

        if not files and not directories:
            return f"No files or directories found for target '{target}'"

        # Cap results to avoid overwhelming context
        truncated = False
        if len(files) + len(directories) > max_results:
            truncated = True
            remaining = max_results
            directories = sorted(directories)[:remaining]
            remaining -= len(directories)
            files = sorted(files)[:max(0, remaining)]
        else:
            directories = sorted(directories)
            files = sorted(files)

        result_parts = []
        if directories:
            result_parts.append(f"Directories ({len(directories)}):\n" + '\n'.join(f"  📁 {d}/" for d in directories))
        if files:
            result_parts.append(f"Files ({len(files)}):\n" + '\n'.join(f"  📄 {f}" for f in files))
        if truncated:
            result_parts.append(f"... truncated to {max_results} results. Narrow your target or disable recursion.")

        return '\n\n'.join(result_parts)

    @classmethod
    def _make_directory(cls, path: str, vault_path: str) -> str:
        """Create directory."""
        full_path = validate_and_resolve_path(path, vault_path)
        os.makedirs(full_path, exist_ok=True)
        return f"Successfully created directory '{path}'"

    @classmethod
    def _search_files(cls, query: str, scope: str, vault_path: str) -> str:
        """Search for text within markdown files using ripgrep."""
        if not query:
            return "Search requires a search pattern in 'target' parameter"

        # Build ripgrep command
        rg_cmd = [
            'rg',
            '--no-heading',
            '--line-number',
            '--color',
            'never',
        ]

        glob_pattern = "*.md"
        search_root = vault_path

        scope = scope.strip()
        if scope:
            if '..' in scope or scope.startswith('/'):
                return "Scope cannot contain '..' or start with '/'"

            # If scope is a directory, search within it with markdown filter
            abs_scope = os.path.join(vault_path, scope)
            if os.path.isdir(abs_scope):
                search_root = abs_scope
                glob_pattern = "*.md"
            else:
                # Treat scope as a glob relative to vault
                glob_pattern = scope

        rg_cmd.extend(['--glob', glob_pattern])

        # Add search pattern
        rg_cmd.append(query)

        # Search in directory
        rg_cmd.append(search_root)

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
                return f"No matches found for '{query}' in markdown files"
            else:
                # Error occurred
                return f"Search error: {result.stderr or 'Unknown error'}"
        except FileNotFoundError:
            return "Error: ripgrep (rg) not found. Please install ripgrep to use search functionality."
        except subprocess.TimeoutExpired:
            return "Search timed out (>10 seconds). Try narrowing your search."
        except Exception as e:
            return f"Search error: {str(e)}"
