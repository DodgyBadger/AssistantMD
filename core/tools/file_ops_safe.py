"""
File operations tool for chat-driven workflows.

Provides secure file management capabilities within vault boundaries.
"""

import os
import glob
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml
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
    get_file_ops_safe_list_max_results,
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
            path: str = "",
            content: str = "",
            destination: str = "",
            include_all: bool = False,
            recursive: bool = False,
            search_term: str = "",
            keys: str = "",
            limit: int = 0,
        ) -> str | ToolReturn:
            """Read/write/list/search/frontmatter markdown files in a vault or virtual mount.

            :param operation: Operation name
            :param path: File, directory, or glob pattern
            :param content: Content for write/append
            :param destination: Destination path for move
            :param include_all: Include non-markdown/hidden files in listings
            :param recursive: Recurse through subdirectories for listings
            :param search_term: Text pattern to search for (search operation)
            :param keys: Comma-separated frontmatter keys to extract (frontmatter operation)
            :param limit: Number of lines to return (head operation)
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

                if operation == "read":
                    if get_virtual_mount_key(path):
                        return cls._read_virtual_mount(path)
                    return cls._read_file(path, vault_path)
                elif operation == "write":
                    if get_virtual_mount_key(path):
                        return cls._deny_virtual_write(path, "write")
                    return cls._write_file(path, content, vault_path)
                elif operation == "append":
                    if get_virtual_mount_key(path):
                        return cls._deny_virtual_write(path, "append")
                    return cls._append_file(path, content, vault_path)
                elif operation == "move":
                    if get_virtual_mount_key(path) or get_virtual_mount_key(destination):
                        return cls._deny_virtual_write(path or destination, "move")
                    return cls._move_file(path, destination, vault_path)
                elif operation == "list":
                    if get_virtual_mount_key(path):
                        return cls._list_virtual_mount(
                            path,
                            include_all=include_all,
                            recursive=recursive,
                            max_results=get_file_ops_safe_list_max_results(),
                        )
                    return cls._list_files(
                        path,
                        vault_path,
                        include_all=include_all,
                        recursive=recursive,
                        max_results=get_file_ops_safe_list_max_results(),
                    )
                elif operation == "mkdir":
                    if get_virtual_mount_key(path):
                        return cls._deny_virtual_write(path, "mkdir")
                    return cls._make_directory(path, vault_path)
                elif operation == "search":
                    return cls._search_files(path, search_term, vault_path)
                elif operation == "frontmatter":
                    return cls._frontmatter_files(path, keys, vault_path)
                elif operation == "head":
                    return cls._head_file(path, limit, vault_path)
                else:
                    return cls._result(
                        message=(
                            f"Unknown operation '{operation}'. "
                            "Available: read, write, append, move, list, mkdir, search, frontmatter, head"
                        ),
                        operation=operation,
                        path=path,
                        destination=destination,
                        search_term=search_term,
                        status="error",
                        error_type="unknown_operation",
                    )

            except Exception as e:
                return cls._result(
                    message=f"Error performing '{operation}' operation: {str(e)}",
                    operation=operation,
                    path=path,
                    destination=destination,
                    search_term=search_term,
                    status="error",
                    error_type=type(e).__name__,
                )

        return Tool(
            file_operations,
            name="file_ops_safe",
            description=(
                "Read, write, append, list, search, frontmatter, "
                "and move files safely within the current vault or virtual mounts. "
                "Prefer this tool over file_ops_unsafe for most operations."
            ),
        )

    @classmethod
    def get_instructions(cls) -> str:
        """Get usage instructions for file operations."""
        return """
Read, write, append, list, search, frontmatter, and move files safely within the current vault or virtual mounts.

Full documentation:
- `__virtual_docs__/tools/file_ops_safe.md`

Important notes:
- start narrow with `operation="list"` or targeted `operation="search"`
- virtual docs are available under `__virtual_docs__/...`
- use `list`, `search`, and `read` on `__virtual_docs__/tools` to inspect tool docs
- writes are non-destructive: no overwrite, delete, or truncate
"""

    @classmethod
    def _result(
        cls,
        *,
        message: str,
        operation: str,
        path: str = "",
        destination: str = "",
        search_term: str = "",
        status: str = "completed",
        exists: bool | None = None,
        error_type: str | None = None,
        content: list[Any] | None = None,
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
        if search_term:
            payload["search_term"] = search_term
        if exists is not None:
            payload["exists"] = exists
        if error_type:
            payload["error_type"] = error_type
        if metadata:
            payload.update(metadata)
        return ToolReturn(return_value=message, content=content, metadata=payload)

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
            return cls._result(
                message=(
                    f"Cannot read '{path}' - this is a directory, not a file. "
                    f"Use file_ops_safe(operation='list', path='{path}') to see files in this directory."
                ),
                operation="read",
                path=path,
                status="invalid_target",
                exists=True,
                error_type="is_directory",
            )

        if not os.path.exists(full_path):
            return cls._result(
                message=(
                    f"Cannot read '{path}' - file does not exist. "
                    "Use file_ops_safe(operation='list') to see available files."
                ),
                operation="read",
                path=path,
                status="not_found",
                exists=False,
                error_type="file_not_found",
            )

        extension = Path(full_path).suffix.lower()
        if extension not in SUPPORTED_READ_FILE_TYPES:
            allowed = ", ".join(sorted(SUPPORTED_READ_FILE_TYPES.keys()))
            return cls._result(
                message=(
                    f"Cannot read '{path}' - unsupported file type '{extension or '[none]'}'. "
                    f"Supported extensions: {allowed}."
                ),
                operation="read",
                path=path,
                status="unsupported",
                exists=True,
                error_type="unsupported_file_type",
                metadata={"extension": extension or "[none]"},
            )

        binary_content = BinaryContent.from_path(full_path)
        if binary_content.is_image:
            max_image_bytes = get_chunking_max_image_bytes_per_image()
            image_size_bytes = len(binary_content.data)
            if max_image_bytes > 0 and image_size_bytes > max_image_bytes:
                max_image_mb = get_chunking_max_image_mb_per_image()
                return cls._result(
                    message=(
                        f"Cannot attach image '{path}' ({image_size_bytes} bytes) - exceeds "
                        f"chunking_max_image_mb_per_image ({max_image_mb} MB)."
                    ),
                    operation="read",
                    path=path,
                    status="unsupported",
                    exists=True,
                    error_type="image_too_large",
                    metadata={
                        "media_mode": "image",
                        "size_bytes": image_size_bytes,
                    },
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
                metadata={
                    "status": "completed",
                    "operation": "read",
                    "path": path,
                    "exists": True,
                    **payload.metadata,
                },
            )

        try:
            with open(full_path, 'r', encoding='utf-8') as file:
                file_content = file.read()
        except UnicodeDecodeError:
            return cls._result(
                message=(
                    f"Cannot read '{path}' as text - this file is binary ({binary_content.media_type}). "
                    "Image files are supported for multimodal reading; other binary types are not supported by "
                    "file_ops_safe(read) yet."
                ),
                operation="read",
                path=path,
                status="unsupported",
                exists=True,
                error_type="binary_file",
                metadata={"media_type": binary_content.media_type},
            )
        if SUPPORTED_READ_FILE_TYPES.get(extension) != "markdown":
            return cls._result(
                message=(
                    f"Cannot read '{path}' as markdown content. "
                    "Only markdown and image files are supported."
                ),
                operation="read",
                path=path,
                status="unsupported",
                exists=True,
                error_type="unsupported_read_mode",
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
                return cls._result(
                    message=(
                        f"Successfully read file '{path}' ({len(file_content)} characters) "
                        f"(image attachments skipped: {decision.reason})\n\n"
                        f"{decision.normalized_text or file_content}"
                    ),
                    operation="read",
                    path=path,
                    status="completed",
                    exists=True,
                    metadata={
                        "media_mode": "markdown",
                        "content_chars": len(file_content),
                        "image_attachments_skipped": True,
                        "image_skip_reason": decision.reason,
                    },
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
                        "status": "completed",
                        "operation": "read",
                        "path": path,
                        "exists": True,
                        "filepath": path,
                        "media_mode": "markdown+images",
                        "attached_image_count": built.attached_image_count,
                        "attached_image_bytes": built.attached_image_bytes,
                        "warnings": built.warnings,
                    },
                )
            return cls._result(
                message=(
                    f"Successfully read file '{path}' ({len(file_content)} characters)\n\n"
                    f"{built.prompt_text}"
                ),
                operation="read",
                path=path,
                status="completed",
                exists=True,
                metadata={
                    "media_mode": "markdown",
                    "content_chars": len(file_content),
                    "attached_image_count": built.attached_image_count,
                    "attached_image_bytes": built.attached_image_bytes,
                },
            )
        return cls._result(
            message=f"Successfully read file '{path}' ({len(file_content)} characters)\n\n{file_content}",
            operation="read",
            path=path,
            status="completed",
            exists=True,
            metadata={
                "media_mode": "markdown",
                "content_chars": len(file_content),
            },
        )

    @classmethod
    def _read_virtual_mount(cls, path: str) -> str:
        """Read file contents from a virtual mount."""
        mount_key = get_virtual_mount_key(path)
        if not mount_key:
            return cls._result(
                message="Invalid virtual mount path",
                operation="read",
                path=path,
                status="invalid_target",
                error_type="invalid_virtual_mount",
            )
        normalized = path.strip().lstrip("./")
        rel = normalized[len(mount_key):].lstrip("/")
        if not rel:
            return cls._result(
                message=(
                    f"Cannot read '{path}' - this is a directory, not a file. "
                    f"Use file_ops_safe(operation=\"list\", path=\"{mount_key}\") to see files."
                ),
                operation="read",
                path=path,
                status="invalid_target",
                exists=True,
                error_type="is_directory",
            )

        # Enforce .md extension (append if missing)
        if "." in os.path.basename(rel) and not rel.endswith(".md"):
            return cls._result(
                message="Only .md files are allowed in virtual mounts",
                operation="read",
                path=path,
                status="unsupported",
                error_type="unsupported_file_type",
            )
        if "." not in os.path.basename(rel):
            rel = f"{rel}.md"

        full_path, _mount = resolve_virtual_path(f"{mount_key}/{rel}")

        if os.path.isdir(full_path):
            return cls._result(
                message=(
                    f"Cannot read '{path}' - this is a directory, not a file. "
                    f"Use file_ops_safe(operation=\"list\", path=\"{path}\") to see files in this directory."
                ),
                operation="read",
                path=path,
                status="invalid_target",
                exists=True,
                error_type="is_directory",
            )

        if not os.path.exists(full_path):
            return cls._result(
                message=f"Cannot read '{path}' - file does not exist.",
                operation="read",
                path=path,
                status="not_found",
                exists=False,
                error_type="file_not_found",
            )

        with open(full_path, 'r', encoding='utf-8') as file:
            file_content = file.read()
        return cls._result(
            message=f"Successfully read file '{path}' ({len(file_content)} characters)\n\n{file_content}",
            operation="read",
            path=path,
            status="completed",
            exists=True,
            metadata={
                "media_mode": "markdown",
                "content_chars": len(file_content),
                "virtual_mount": mount_key,
            },
        )

    @classmethod
    def _write_file(cls, path: str, content: str, vault_path: str) -> str:
        """Write new file (fails if exists)."""
        full_path = validate_and_resolve_path(path, vault_path)

        if os.path.exists(full_path):
            return cls._result(
                message=(
                    f"Cannot write to '{path}' - file already exists. "
                    "Use 'append' operation to add content to existing files."
                ),
                operation="write",
                path=path,
                status="already_exists",
                exists=True,
                error_type="file_exists",
            )

        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w', encoding='utf-8') as file:
            file.write(content)
        return cls._result(
            message=f"Successfully created new file '{path}' with {len(content)} characters",
            operation="write",
            path=path,
            status="completed",
            exists=True,
            metadata={"content_chars": len(content)},
        )

    @classmethod
    def _append_file(cls, path: str, content: str, vault_path: str) -> str:
        """Append to existing file."""
        full_path = validate_and_resolve_path(path, vault_path)

        if not os.path.exists(full_path):
            return cls._result(
                message=(
                    f"Cannot append to '{path}' - file does not exist. "
                    "Use 'write' operation to create new files."
                ),
                operation="append",
                path=path,
                status="not_found",
                exists=False,
                error_type="file_not_found",
            )

        with open(full_path, 'a', encoding='utf-8') as file:
            file.write(content)
        return cls._result(
            message=f"Successfully appended {len(content)} characters to '{path}'",
            operation="append",
            path=path,
            status="completed",
            exists=True,
            metadata={"content_chars": len(content)},
        )

    @classmethod
    def _move_file(cls, path: str, destination: str, vault_path: str) -> str:
        """Move file to new location."""
        src_path = validate_and_resolve_path(path, vault_path)
        dest_path = validate_and_resolve_path(destination, vault_path)

        if not os.path.exists(src_path):
            return cls._result(
                message=f"Cannot move '{path}' - source file does not exist",
                operation="move",
                path=path,
                destination=destination,
                status="not_found",
                exists=False,
                error_type="source_not_found",
            )

        if os.path.exists(dest_path):
            return cls._result(
                message=(
                    f"Cannot move '{path}' to '{destination}' - destination already exists. "
                    "Choose a different destination path."
                ),
                operation="move",
                path=path,
                destination=destination,
                status="already_exists",
                exists=True,
                error_type="destination_exists",
            )

        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        shutil.move(src_path, dest_path)
        return cls._result(
            message=f"Successfully moved '{path}' to '{destination}'",
            operation="move",
            path=path,
            destination=destination,
            status="completed",
            exists=True,
        )

    @classmethod
    def _list_files(
        cls,
        path: str,
        vault_path: str,
        include_all: bool,
        recursive: bool,
        max_results: int,
    ) -> ToolReturn:
        """List files and directories matching a path or glob."""
        path = path.strip()
        if not path or path == ".":
            path = "*"

        if '..' in path or path.startswith('/'):
            raise ValueError("Path cannot contain '..' or start with '/'")

        is_glob = any(ch in path for ch in "*?[")
        if not is_glob:
            abs_path = os.path.join(vault_path, path)
            if os.path.isdir(abs_path):
                path = os.path.join(path, "**/*" if recursive else "*")

        full_pattern = os.path.join(vault_path, path)
        matches = glob.glob(full_pattern, recursive=recursive or "**" in path)

        files = []
        directories = []

        for match in matches:
            if not match.startswith(vault_path + os.sep) and match != vault_path:
                continue

            relative_path = match[len(vault_path) + 1:] if match != vault_path else ""

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
            return cls._result(
                message=f"No files or directories found for path '{path}'",
                operation="list",
                path=path,
                status="completed",
                exists=True,
                metadata={
                    "directory_count": 0,
                    "file_count": 0,
                    "directories": [],
                    "files": [],
                    "truncated": False,
                },
            )

        truncated = False
        if max_results > 0 and len(files) + len(directories) > max_results:
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
            result_parts.append(f"... truncated to {max_results} results. Narrow your path or disable recursion.")

        return cls._result(
            message='\n\n'.join(result_parts),
            operation="list",
            path=path,
            status="completed",
            exists=True,
            metadata={
                "directory_count": len(directories),
                "file_count": len(files),
                "directories": directories,
                "files": files,
                "truncated": truncated,
            },
        )

    @classmethod
    def _list_virtual_mount(
        cls,
        path: str,
        include_all: bool,
        recursive: bool,
        max_results: int,
    ) -> ToolReturn:
        """List files and directories under a virtual mount."""
        path = path.strip()
        mount_key = get_virtual_mount_key(path) or ""
        if not path or path == mount_key:
            path = mount_key

        normalized = path.strip().lstrip("./")
        rel = normalized[len(mount_key):].lstrip("/")

        if ".." in rel.split(os.sep):
            raise ValueError("Path cannot contain '..' for virtual mounts")

        docs_root, _mount = resolve_virtual_path(mount_key)

        is_glob = any(ch in rel for ch in "*?[")
        if not rel:
            rel = "*"
        elif not is_glob:
            abs_path = os.path.join(docs_root, rel)
            if os.path.isdir(abs_path):
                rel = os.path.join(rel, "**/*" if recursive else "*")

        full_pattern = os.path.join(docs_root, rel)
        matches = glob.glob(full_pattern, recursive=recursive or "**" in rel)

        files = []
        directories = []

        for match in matches:
            if not match.startswith(docs_root + os.sep) and match != docs_root:
                continue

            relative_path = match[len(docs_root) + 1:] if match != docs_root else ""

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
            return cls._result(
                message=f"No files or directories found for path '{path}'",
                operation="list",
                path=path,
                status="completed",
                exists=True,
                metadata={
                    "directory_count": 0,
                    "file_count": 0,
                    "directories": [],
                    "files": [],
                    "truncated": False,
                    "virtual_mount": mount_key,
                },
            )

        truncated = False
        if max_results > 0 and len(files) + len(directories) > max_results:
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
            result_parts.append(f"... truncated to {max_results} results. Narrow your path or disable recursion.")

        return cls._result(
            message='\n\n'.join(result_parts),
            operation="list",
            path=path,
            status="completed",
            exists=True,
            metadata={
                "directory_count": len(directories),
                "file_count": len(files),
                "directories": [f"{mount_key}/{d}" for d in directories],
                "files": [f"{mount_key}/{f}" for f in files],
                "truncated": truncated,
                "virtual_mount": mount_key,
            },
        )

    @classmethod
    def _deny_virtual_write(cls, path: str, operation: str) -> str:
        mount_key = get_virtual_mount_key(path) or "__virtual_docs__"
        return cls._result(
            message=f"{operation} not allowed for '{mount_key}' (read-only virtual mount)",
            operation=operation,
            path=path,
            status="unsupported",
            error_type="virtual_mount_read_only",
        )

    @classmethod
    def _make_directory(cls, path: str, vault_path: str) -> str:
        """Create directory."""
        full_path = validate_and_resolve_path(path, vault_path)
        os.makedirs(full_path, exist_ok=True)
        return cls._result(
            message=f"Successfully created directory '{path}'",
            operation="mkdir",
            path=path,
            status="completed",
            exists=True,
        )

    @classmethod
    def _search_files(cls, path: str, search_term: str, vault_path: str) -> ToolReturn:
        """Search for text within markdown files using ripgrep."""
        search_term = search_term.strip()
        if not search_term:
            return cls._result(
                message="Search requires a search pattern in 'search_term' parameter",
                operation="search",
                path=path,
                search_term=search_term,
                status="error",
                error_type="missing_query",
            )

        vault_abs = os.path.realpath(vault_path)

        rg_cmd = [
            'rg',
            '--no-heading',
            '--with-filename',
            '--line-number',
            '--color',
            'never',
            '--ignore-case',
        ]

        glob_pattern = "*.md"
        search_root = vault_abs
        result_base_root = vault_abs
        result_prefix = ""

        path = path.strip()
        if path:
            if '..' in path or path.startswith('/'):
                return cls._result(
                    message="Path cannot contain '..' or start with '/'",
                    operation="search",
                    path=path,
                    search_term=search_term,
                    status="invalid_target",
                    error_type="invalid_path",
                )

            mount_key = get_virtual_mount_key(path)
            if mount_key:
                root, _mount = resolve_virtual_path(mount_key)
                root_abs = os.path.realpath(root)
                rel = path.strip().lstrip("./")[len(mount_key):].lstrip("/")
                if rel:
                    abs_scope = os.path.realpath(os.path.join(root_abs, rel))
                else:
                    abs_scope = root_abs

                if os.path.isdir(abs_scope):
                    if (
                        not abs_scope.startswith(root_abs + os.sep)
                        and abs_scope != root_abs
                    ):
                        return cls._result(
                            message="Path escapes virtual mount boundaries",
                            operation="search",
                            path=path,
                            search_term=search_term,
                            status="invalid_target",
                            error_type="path_escapes_mount",
                        )
                    search_root = abs_scope
                    glob_pattern = "*.md"
                elif os.path.isfile(abs_scope):
                    if (
                        not abs_scope.startswith(root_abs + os.sep)
                        and abs_scope != root_abs
                    ):
                        return cls._result(
                            message="Path escapes virtual mount boundaries",
                            operation="search",
                            path=path,
                            search_term=search_term,
                            status="invalid_target",
                            error_type="path_escapes_mount",
                        )
                    search_root = abs_scope
                    glob_pattern = "*.md"
                else:
                    search_root = root_abs
                    glob_pattern = rel
                result_base_root = root_abs
                result_prefix = mount_key
            else:
                abs_scope = os.path.realpath(os.path.join(vault_abs, path))
                if os.path.isdir(abs_scope):
                    if (
                        not abs_scope.startswith(vault_abs + os.sep)
                        and abs_scope != vault_abs
                    ):
                        return cls._result(
                            message="Path escapes vault boundaries",
                            operation="search",
                            path=path,
                            search_term=search_term,
                            status="invalid_target",
                            error_type="path_escapes_vault",
                        )
                    search_root = abs_scope
                    glob_pattern = "*.md"
                elif os.path.isfile(abs_scope):
                    if (
                        not abs_scope.startswith(vault_abs + os.sep)
                        and abs_scope != vault_abs
                    ):
                        return cls._result(
                            message="Path escapes vault boundaries",
                            operation="search",
                            path=path,
                            search_term=search_term,
                            status="invalid_target",
                            error_type="path_escapes_vault",
                        )
                    search_root = abs_scope
                    glob_pattern = "*.md"
                else:
                    glob_pattern = path

        rg_cmd.extend(['--glob', glob_pattern])
        rg_cmd.append(search_term)
        rg_cmd.append(search_root)

        try:
            result = subprocess.run(
                rg_cmd,
                capture_output=True,
                text=True,
                timeout=get_file_search_timeout_seconds(),
            )

            if result.returncode == 0:
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
                        rel_path = file_path
                    if rel_path == ".":
                        rel_path = os.path.basename(file_path)
                    if result_prefix:
                        rel_path = f"{result_prefix}/{rel_path}"
                    lines.append(f"{rel_path}:{line_no}:{line_content}")

                return cls._result(
                    message=f"Found {len(lines)} matches:\n\n" + '\n'.join(lines),
                    operation="search",
                    path=path,
                    search_term=search_term,
                    status="completed",
                    exists=True,
                    metadata={
                        "match_count": len(lines),
                        "matches": lines,
                    },
                )
            elif result.returncode == 1:
                return cls._result(
                    message=f"No matches found for '{search_term}' in markdown files",
                    operation="search",
                    path=path,
                    search_term=search_term,
                    status="completed",
                    exists=True,
                    metadata={"match_count": 0, "matches": []},
                )
            else:
                return cls._result(
                    message=f"Search error: {result.stderr or 'Unknown error'}",
                    operation="search",
                    path=path,
                    search_term=search_term,
                    status="error",
                    error_type="search_failed",
                )
        except FileNotFoundError:
            return cls._result(
                message="Error: ripgrep (rg) not found. Please install ripgrep to use search functionality.",
                operation="search",
                path=path,
                search_term=search_term,
                status="error",
                error_type="ripgrep_not_found",
            )
        except subprocess.TimeoutExpired:
            timeout_seconds = get_file_search_timeout_seconds()
            return cls._result(
                message=f"Search timed out (>{timeout_seconds:g} seconds). Try narrowing your search.",
                operation="search",
                path=path,
                search_term=search_term,
                status="error",
                error_type="timeout",
            )
        except Exception as e:
            return cls._result(
                message=f"Search error: {str(e)}",
                operation="search",
                path=path,
                search_term=search_term,
                status="error",
                error_type=type(e).__name__,
            )

    @classmethod
    def _frontmatter_files(cls, path: str, keys: str, vault_path: str) -> ToolReturn:
        """Extract frontmatter from markdown files matching path or glob."""
        path = path.strip()
        if not path or path == ".":
            path = "*"

        if '..' in path or path.startswith('/'):
            raise ValueError("Path cannot contain '..' or start with '/'")

        is_glob = any(ch in path for ch in "*?[")
        if not is_glob:
            abs_path = os.path.join(vault_path, path)
            if os.path.isdir(abs_path):
                path = os.path.join(path, "*")

        full_pattern = os.path.join(vault_path, path)
        matches = sorted(glob.glob(full_pattern, recursive=False))

        vault_abs = os.path.realpath(vault_path)
        md_files: list[tuple[str, str]] = []
        for match in matches:
            if not match.endswith(".md"):
                continue
            abs_match = os.path.realpath(match)
            if not abs_match.startswith(vault_abs + os.sep):
                continue
            rel = abs_match[len(vault_abs) + 1:]
            if any(part.startswith('.') for part in rel.split(os.sep)):
                continue
            md_files.append((rel, abs_match))

        if not md_files:
            return cls._result(
                message=f"No markdown files found for path '{path}'",
                operation="frontmatter",
                path=path,
                status="completed",
                metadata={"file_count": 0, "items": []},
            )

        filter_keys = [k.strip() for k in keys.split(",") if k.strip()] if keys else []

        items: list[dict[str, Any]] = []
        for rel_path, abs_path in md_files:
            try:
                with open(abs_path, 'r', encoding='utf-8') as f:
                    raw = f.read()
                fm = cls._parse_frontmatter(raw)
                if filter_keys:
                    fm = {k: fm[k] for k in filter_keys if k in fm}
                items.append({"path": rel_path, "frontmatter": fm})
            except Exception:
                items.append({"path": rel_path, "frontmatter": {}})

        lines = []
        for item in items:
            fm_parts = ", ".join(f"{k}: {v}" for k, v in item["frontmatter"].items())
            lines.append(f"  {item['path']}: {{{fm_parts}}}")

        return cls._result(
            message=f"Frontmatter for {len(items)} file(s):\n" + "\n".join(lines),
            operation="frontmatter",
            path=path,
            status="completed",
            metadata={"file_count": len(items), "items": items},
        )

    @classmethod
    def _head_file(cls, path: str, limit: int, vault_path: str) -> ToolReturn:
        """Read first N lines of a file."""
        full_path = cls._validate_read_path(path, vault_path)

        if not os.path.exists(full_path):
            return cls._result(
                message=f"Cannot read '{path}' - file does not exist.",
                operation="head",
                path=path,
                status="not_found",
                exists=False,
                error_type="file_not_found",
            )

        if os.path.isdir(full_path):
            return cls._result(
                message=f"Cannot read '{path}' - this is a directory.",
                operation="head",
                path=path,
                status="invalid_target",
                exists=True,
                error_type="is_directory",
            )

        n = limit if limit > 0 else 20
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                head_lines = []
                for _ in range(n):
                    line = f.readline()
                    if not line:
                        break
                    head_lines.append(line)
            text = "".join(head_lines)
            return cls._result(
                message=f"First {len(head_lines)} lines of '{path}':\n\n{text}",
                operation="head",
                path=path,
                status="completed",
                exists=True,
                metadata={"lines_returned": len(head_lines), "limit": n},
            )
        except UnicodeDecodeError:
            return cls._result(
                message=f"Cannot read '{path}' as text - binary file.",
                operation="head",
                path=path,
                status="unsupported",
                exists=True,
                error_type="binary_file",
            )

    @staticmethod
    def _parse_frontmatter(content: str) -> dict[str, Any]:
        """Parse YAML frontmatter from markdown content."""
        if not content.startswith("---"):
            return {}
        end = content.find("\n---", 3)
        if end == -1:
            return {}
        fm_text = content[3:end].strip()
        try:
            result = yaml.safe_load(fm_text)
            return result if isinstance(result, dict) else {}
        except Exception:
            return {}
