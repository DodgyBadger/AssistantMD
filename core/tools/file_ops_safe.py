"""
File operations tool for chat-driven workflows.

Provides secure file management capabilities within vault boundaries.
"""

import os
import glob
import shutil
import subprocess
from pathlib import Path

from pydantic_ai.messages import BinaryContent, ToolReturn
from pydantic_ai.tools import Tool

from core.chunking import (
    build_input_files_prompt,
    default_chunking_policy,
    evaluate_markdown_image_policy,
    parse_markdown_chunks,
)
from core.constants import SUPPORTED_READ_FILE_TYPES
from core.logger import UnifiedLogger
from core.settings import (
    get_auto_buffer_max_tokens,
    get_chunking_max_image_bytes_per_image,
    get_chunking_max_image_mb_per_image,
    get_file_search_timeout_seconds,
)
from core.utils.image_inputs import build_image_tool_payload
from .base import BaseTool
from .utils import (
    validate_and_resolve_path,
    resolve_virtual_path,
    get_virtual_mount_key,
)


logger = UnifiedLogger(tag="file-ops-safe-tool")


class FileOpsSafe(BaseTool):
    """Safe file operations tool with vault boundary enforcement."""

    @classmethod
    def get_tool(cls, vault_path: str = None):
        """Get the Pydantic AI tool for file operations.

        :param vault_path: Path to vault for file operations scope
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
        ) -> str | ToolReturn:
            """Read/write/list/search markdown files in a vault or virtual mount.

            :param operation: Operation name
            :param target: File, directory, or glob pattern
            :param content: Content for write/append
            :param destination: Destination path for move
            :param include_all: Include non-markdown/hidden files in listings
            :param recursive: Recurse through subdirectories for listings
            :param scope: Folder or glob to limit search
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
                    if get_virtual_mount_key(target):
                        return cls._read_virtual_mount(target)
                    return cls._read_file(target, vault_path)
                elif operation == "write":
                    if get_virtual_mount_key(target):
                        return cls._deny_virtual_write(target, "write")
                    return cls._write_file(target, content, vault_path)
                elif operation == "append":
                    if get_virtual_mount_key(target):
                        return cls._deny_virtual_write(target, "append")
                    return cls._append_file(target, content, vault_path)
                elif operation == "move":
                    if get_virtual_mount_key(target) or get_virtual_mount_key(destination):
                        return cls._deny_virtual_write(target or destination, "move")
                    return cls._move_file(target, destination, vault_path)
                elif operation == "list":
                    if get_virtual_mount_key(target):
                        return cls._list_virtual_mount(target, include_all=include_all, recursive=recursive)
                    return cls._list_files(target, vault_path, include_all=include_all, recursive=recursive)
                elif operation == "mkdir":
                    if get_virtual_mount_key(target):
                        return cls._deny_virtual_write(target, "mkdir")
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
        return """
## file_ops_safe usage instructions
        
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
- Search is case-insensitive and trims leading/trailing spaces in target
- If a scoped search unexpectedly returns no matches, run list on that scope first to verify directory/glob shape
- Results show: filename:line_number:matching_line_content
- Search returns all matches (very large outputs may be auto-buffered by routing settings)

⚠️ CONTEXT WINDOW WARNING: Avoid broad searches and recursive lists.
Instead, explore the vault structure first, then target specific folders or file types.

READING & WRITING:
- file_ops_safe(operation="read", target="path/to/file.md"): Read file content
- file_ops_safe(operation="read", target="path/to/image.png"): Attach image content for vision-capable models
- file_ops_safe(operation="read", target="path/to/note.md"): If markdown embeds local images, returns ordered multimodal content
- file_ops_safe(operation="write", target="path/to/file.md", content="text"): Create NEW file (fails if exists)
- file_ops_safe(operation="append", target="path/to/file.md", content="text"): Append to EXISTING file (fails if not exists)
- file_ops_safe(operation="move", target="old/path.md", destination="new/path.md"): Move files (fails if destination exists)
- file_ops_safe(operation="mkdir", target="path/to/directory"): Create directories

BEST PRACTICES:
1. Start exploration with file_ops_safe(operation="list") to see vault structure
2. Use 'search' to find content across files efficiently
3. Navigate into relevant directories before doing recursive searches
4. Read only files relevant to the user's request
5. Write/append operations require .md files; read also supports image files
6. All operations are SAFE - no overwriting or data loss
"""


    @classmethod
    def _validate_read_path(cls, path: str, vault_path: str) -> str:
        """Validate read path within vault boundaries, allowing non-markdown files."""
        mount_key = get_virtual_mount_key(path)
        if mount_key:
            raise ValueError(f"'{mount_key}' is reserved for a virtual mount")
        if ".." in path:
            raise ValueError("Path traversal not allowed - '..' found in path")
        if path.startswith("/"):
            raise ValueError("Absolute paths not allowed")

        full_path = os.path.join(vault_path, path)
        resolved_path = os.path.realpath(full_path)
        vault_abs = os.path.realpath(vault_path)
        if not resolved_path.startswith(vault_abs + os.sep) and resolved_path != vault_abs:
            raise ValueError("Path escapes vault boundaries")
        return resolved_path

    @classmethod
    def _read_file(cls, path: str, vault_path: str) -> str | ToolReturn:
        """Read file contents."""
        full_path = cls._validate_read_path(path, vault_path)

        if os.path.isdir(full_path):
            return f"Cannot read '{path}' - this is a directory, not a file. Use file_operations('list', target='{path}') to see files in this directory."

        if not os.path.exists(full_path):
            return f"Cannot read '{path}' - file does not exist. Use file_operations('list') to see available files."

        extension = Path(full_path).suffix.lower()
        if extension not in SUPPORTED_READ_FILE_TYPES:
            allowed = ", ".join(sorted(SUPPORTED_READ_FILE_TYPES.keys()))
            return (
                f"Cannot read '{path}' - unsupported file type '{extension or '[none]'}'. "
                f"Supported extensions: {allowed}."
            )

        binary_content = BinaryContent.from_path(full_path)
        if binary_content.is_image:
            max_image_bytes = get_chunking_max_image_bytes_per_image()
            image_size_bytes = len(binary_content.data)
            if image_size_bytes > max_image_bytes:
                max_image_mb = get_chunking_max_image_mb_per_image()
                return (
                    f"Cannot attach image '{path}' ({image_size_bytes} bytes) - exceeds "
                    f"chunking_max_image_mb_per_image ({max_image_mb} MB)."
                )
            payload = build_image_tool_payload(
                image_path=Path(full_path),
                vault_path=vault_path,
            )
            return ToolReturn(
                return_value=(
                    f"Attached image '{payload.metadata['filepath']}' "
                    f"({payload.metadata['media_type']}, {payload.metadata['size_bytes']} bytes)."
                ),
                content=[payload.note, payload.image_blob],
                metadata=payload.metadata,
            )

        try:
            with open(full_path, 'r', encoding='utf-8') as file:
                file_content = file.read()
        except UnicodeDecodeError:
            return (
                f"Cannot read '{path}' as text - this file is binary ({binary_content.media_type}). "
                "Image files are supported for multimodal reading; other binary types are not supported by "
                "file_ops_safe(read) yet."
            )
        if SUPPORTED_READ_FILE_TYPES.get(extension) != "markdown":
            return (
                f"Cannot read '{path}' as markdown content. "
                "Only markdown and image files are supported."
            )
        markdown_chunks = parse_markdown_chunks(file_content)
        has_embedded_images = any(chunk.kind == "image_ref" for chunk in markdown_chunks)
        if has_embedded_images:
            decision = evaluate_markdown_image_policy(
                file_content=file_content,
                markdown_chunks=markdown_chunks,
                source_markdown_path=path,
                vault_path=vault_path,
                auto_buffer_max_tokens=get_auto_buffer_max_tokens(),
                policy=default_chunking_policy(),
            )
            if not decision.attach_images:
                return (
                    f"Successfully read file '{path}' ({len(file_content)} characters) "
                    f"(image attachments skipped: {decision.reason})\n\n"
                    f"{decision.normalized_text or file_content}"
                )

            built = build_input_files_prompt(
                input_file_data=[
                    {
                        "filepath": path,
                        "source_path": path,
                        "filename": Path(path).stem,
                        "content": file_content,
                        "found": True,
                        "error": None,
                        "images_policy": "auto",
                    }
                ],
                vault_path=vault_path,
                include_file_framing=False,
                supports_vision=None,
            )
            if isinstance(built.prompt, list):
                return ToolReturn(
                    return_value=(
                        f"Successfully read markdown file '{path}' with embedded images "
                        f"({built.attached_image_count} image attachment(s), "
                        f"{built.attached_image_bytes} bytes)."
                    ),
                    content=built.prompt,
                    metadata={
                        "filepath": path,
                        "media_mode": "markdown+images",
                        "attached_image_count": built.attached_image_count,
                        "attached_image_bytes": built.attached_image_bytes,
                        "warnings": built.warnings,
                    },
                )
            return (
                f"Successfully read file '{path}' ({len(file_content)} characters)\n\n"
                f"{built.prompt_text}"
            )
        return f"Successfully read file '{path}' ({len(file_content)} characters)\n\n{file_content}"

    @classmethod
    def _read_virtual_mount(cls, path: str) -> str:
        """Read file contents from a virtual mount."""
        mount_key = get_virtual_mount_key(path)
        if not mount_key:
            return "Invalid virtual mount path"
        normalized = path.strip().lstrip("./")
        rel = normalized[len(mount_key):].lstrip("/")
        if not rel:
            return f"Cannot read '{path}' - this is a directory, not a file. Use file_ops_safe(operation=\"list\", target=\"{mount_key}\") to see files."

        # Enforce .md extension (append if missing)
        if "." in os.path.basename(rel) and not rel.endswith(".md"):
            return "Only .md files are allowed in virtual mounts"
        if "." not in os.path.basename(rel):
            rel = f"{rel}.md"

        full_path, _mount = resolve_virtual_path(f"{mount_key}/{rel}")

        if os.path.isdir(full_path):
            return f"Cannot read '{path}' - this is a directory, not a file. Use file_ops_safe(operation=\"list\", target=\"{path}\") to see files in this directory."

        if not os.path.exists(full_path):
            return f"Cannot read '{path}' - file does not exist."

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
    def _list_virtual_mount(cls, target: str, include_all: bool, recursive: bool, max_results: int = 200) -> str:
        """List files and directories under a virtual mount."""
        target = target.strip()
        mount_key = get_virtual_mount_key(target) or ""
        if not target or target == mount_key:
            target = mount_key

        normalized = target.strip().lstrip("./")
        rel = normalized[len(mount_key):].lstrip("/")

        if ".." in rel.split(os.sep):
            raise ValueError("Target cannot contain '..' for virtual mounts")

        docs_root, _mount = resolve_virtual_path(mount_key)

        # If target points to a directory (no glob), list its immediate contents
        is_glob = any(ch in rel for ch in "*?[")
        if not rel:
            rel = "*"
        elif not is_glob:
            abs_target = os.path.join(docs_root, rel)
            if os.path.isdir(abs_target):
                rel = os.path.join(rel, "**/*" if recursive else "*")

        full_pattern = os.path.join(docs_root, rel)
        matches = glob.glob(full_pattern, recursive=recursive or "**" in rel)

        files = []
        directories = []

        for match in matches:
            if not match.startswith(docs_root + os.sep) and match != docs_root:
                continue

            relative_path = match[len(docs_root) + 1:] if match != docs_root else ""

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
            result_parts.append(f"Directories ({len(directories)}):\n" + '\n'.join(f"  📁 {mount_key}/{d}/" for d in directories))
        if files:
            result_parts.append(f"Files ({len(files)}):\n" + '\n'.join(f"  📄 {mount_key}/{f}" for f in files))
        if truncated:
            result_parts.append(f"... truncated to {max_results} results. Narrow your target or disable recursion.")

        return '\n\n'.join(result_parts)

    @classmethod
    def _deny_virtual_write(cls, target: str, operation: str) -> str:
        mount_key = get_virtual_mount_key(target) or "__virtual_docs__"
        return f"{operation} not allowed for '{mount_key}' (read-only virtual mount)"

    @classmethod
    def _make_directory(cls, path: str, vault_path: str) -> str:
        """Create directory."""
        full_path = validate_and_resolve_path(path, vault_path)
        os.makedirs(full_path, exist_ok=True)
        return f"Successfully created directory '{path}'"

    @classmethod
    def _search_files(cls, query: str, scope: str, vault_path: str) -> str:
        """Search for text within markdown files using ripgrep."""
        query = query.strip()
        if not query:
            return "Search requires a search pattern in 'target' parameter"

        vault_abs = os.path.realpath(vault_path)

        # Build ripgrep command
        rg_cmd = [
            'rg',
            '--no-heading',
            '--line-number',
            '--color',
            'never',
            '--ignore-case',
        ]

        glob_pattern = "*.md"
        search_root = vault_abs
        result_base_root = vault_abs
        result_prefix = ""

        scope = scope.strip()
        if scope:
            if '..' in scope or scope.startswith('/'):
                return "Scope cannot contain '..' or start with '/'"

            mount_key = get_virtual_mount_key(scope)
            if mount_key:
                root, _mount = resolve_virtual_path(mount_key)
                root_abs = os.path.realpath(root)
                rel = scope.strip().lstrip("./")[len(mount_key):].lstrip("/")
                if rel:
                    abs_scope = os.path.realpath(os.path.join(root_abs, rel))
                else:
                    abs_scope = root_abs

                if os.path.isdir(abs_scope):
                    if (
                        not abs_scope.startswith(root_abs + os.sep)
                        and abs_scope != root_abs
                    ):
                        return "Scope escapes virtual mount boundaries"
                    search_root = abs_scope
                    glob_pattern = "*.md"
                else:
                    # Treat rel as a glob relative to docs root
                    search_root = root_abs
                    glob_pattern = rel
                result_base_root = root_abs
                result_prefix = mount_key
            else:
                # If scope is a directory, search within it with markdown filter
                abs_scope = os.path.realpath(os.path.join(vault_abs, scope))
                if os.path.isdir(abs_scope):
                    if (
                        not abs_scope.startswith(vault_abs + os.sep)
                        and abs_scope != vault_abs
                    ):
                        return "Scope escapes vault boundaries"
                    search_root = abs_scope
                    glob_pattern = "*.md"
                else:
                    # Treat scope as a glob relative to vault
                    glob_pattern = scope

        # If caller used virtual docs prefix in target (query), that's a mistake
        # Keep behavior consistent: only scope controls search root.

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
                timeout=get_file_search_timeout_seconds(),
            )

            if result.returncode == 0:
                # Normalize paths so the model sees logical (root-relative) paths.
                # ripgrep output is file_path:line_number:line_content
                lines = []
                for raw_line in result.stdout.splitlines():
                    file_path, sep, remainder = raw_line.partition(':')
                    if not sep:
                        lines.append(raw_line)
                        continue
                    line_no, sep2, line_content = remainder.partition(':')
                    if not sep2:
                        lines.append(raw_line)
                        continue

                    file_abs = os.path.realpath(file_path)
                    try:
                        rel_path = os.path.relpath(file_abs, result_base_root)
                    except ValueError:
                        # Fallback for unexpected path formats.
                        rel_path = file_path
                    if rel_path == ".":
                        rel_path = os.path.basename(file_path)
                    if result_prefix:
                        rel_path = f"{result_prefix}/{rel_path}"
                    lines.append(f"{rel_path}:{line_no}:{line_content}")

                return f"Found {len(lines)} matches:\n\n" + '\n'.join(lines)
            elif result.returncode == 1:
                # No matches found
                return f"No matches found for '{query}' in markdown files"
            else:
                # Error occurred
                return f"Search error: {result.stderr or 'Unknown error'}"
        except FileNotFoundError:
            return "Error: ripgrep (rg) not found. Please install ripgrep to use search functionality."
        except subprocess.TimeoutExpired:
            timeout_seconds = get_file_search_timeout_seconds()
            return f"Search timed out (>{timeout_seconds:g} seconds). Try narrowing your search."
        except Exception as e:
            return f"Search error: {str(e)}"
