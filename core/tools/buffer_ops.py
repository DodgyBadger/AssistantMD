"""
Buffer operations tool for run-scoped in-memory variables.

Read-only tool aligned with file_ops_safe patterns.
"""

from __future__ import annotations

import re

from pydantic_ai import RunContext
from pydantic_ai.tools import Tool

from core.constants import (
    BUFFER_PEEK_MAX_CHARS,
    BUFFER_READ_MAX_CHARS,
    BUFFER_SEARCH_MAX_MATCHES,
    BUFFER_SEARCH_CONTEXT_CHARS,
)
from core.logger import UnifiedLogger
from .base import BaseTool


logger = UnifiedLogger(tag="buffer-ops-tool")


class BufferOps(BaseTool):
    """Read-only buffer operations within run-scoped buffer store."""

    @classmethod
    def get_tool(cls, vault_path: str | None = None):
        """Get the Pydantic AI tool for buffer operations."""

        def buffer_operations(
            ctx: RunContext,
            *,
            operation: str,
            target: str = "",
            query: str = "",
            scope: str = "",
            offset: int = 0,
            length: int = 0,
            start_line: int = 0,
            end_line: int = 0,
            max_chars: int = 0,
        ) -> str:
            """Perform read-only buffer operations.

            :param operation: Operation name (list, info, peek, read, search)
            :param target: Buffer name (no variable: prefix)
            :param query: Regex pattern for search
            :param scope: Buffer name for search (alias for target)
            :param offset: Character offset for peek/read
            :param length: Character length for read
            :param start_line: 1-based start line for read
            :param end_line: 1-based end line for read (inclusive)
            :param max_chars: Maximum characters for peek
            """
            try:
                logger.set_sinks(["validation"]).info(
                    "tool_invoked",
                    data={"tool": "buffer_ops"},
                )
                buffer_store = getattr(ctx, "deps", None) and ctx.deps.buffer_store
                if buffer_store is None:
                    return "Buffer store unavailable for buffer_ops"

                op = (operation or "").strip().lower()
                if op == "list":
                    return cls._list_buffers(buffer_store)
                if op == "info":
                    return cls._buffer_info(buffer_store, target)
                if op == "peek":
                    return cls._peek_buffer(buffer_store, target, offset, max_chars)
                if op == "read":
                    return cls._read_buffer(buffer_store, target, offset, length, start_line, end_line)
                if op == "search":
                    return cls._search_buffer(buffer_store, target, scope, query)
                return "Unknown operation. Available: list, info, peek, read, search"
            except Exception as exc:
                return f"Error performing '{operation}' operation: {str(exc)}"

        return Tool(buffer_operations, name="buffer_ops")

    @classmethod
    def get_instructions(cls) -> str:
        """Get usage instructions for buffer operations."""
        return """
      
DISCOVERY:
- buffer_ops(operation="list")
- buffer_ops(operation="info", target="buffer_name")

READING:
- buffer_ops(operation="peek", target="buffer_name", offset=0, max_chars=1000)
- buffer_ops(operation="read", target="buffer_name", start_line=1, end_line=200)
- buffer_ops(operation="read", target="buffer_name", offset=0, length=2000)

SEARCH (regex):
- buffer_ops(operation="search", target="buffer_name", query="TODO")
- buffer_ops(operation="search", scope="buffer_name", query="\\berror\\b")

NOTES:
- All reads are capped to keep outputs small.
- Use search + read ranges instead of trying to read full buffers.
- For large buffers: start with info/preview, then search for anchors, then read nearby line ranges.
- Target is the buffer name only (no 'variable:' prefix).
"""

    @staticmethod
    def _list_buffers(buffer_store) -> str:
        buffers = buffer_store.list()
        if not buffers:
            return "No buffers available."

        lines = ["Buffers:"]
        for name in sorted(buffers.keys()):
            meta = buffers[name]
            updated = meta.get("updated_at")
            updated_str = updated.isoformat() if updated else "unknown"
            lines.append(f"- {name}: {meta.get('size', 0)} chars (updated {updated_str})")
        return "\n".join(lines)

    @staticmethod
    def _buffer_info(buffer_store, name: str) -> str:
        name = (name or "").strip()
        if not name:
            return "Buffer name is required for info."
        entry = buffer_store.get(name)
        if entry is None:
            return f"Buffer '{name}' not found."
        meta = entry.metadata or {}
        content = entry.content or ""
        line_count = len(content.splitlines())
        from core.tools.utils import estimate_token_count
        token_count = estimate_token_count(content) if content else 0
        preview_limit = 500
        preview = content[:preview_limit]
        return "\n".join(
            [
                f"Buffer: {name}",
                f"Size: {len(content)} chars",
                f"Lines: {line_count}",
                f"Tokens: {token_count}",
                f"Metadata: {meta}",
                "",
                f"Preview (first {preview_limit} chars):",
                preview,
            ]
        )

    @staticmethod
    def _peek_buffer(buffer_store, name: str, offset: int, max_chars: int) -> str:
        name = (name or "").strip()
        if not name:
            return "Buffer name is required for peek."
        entry = buffer_store.get(name)
        if entry is None:
            return f"Buffer '{name}' not found."
        content = entry.content or ""
        safe_offset = max(0, int(offset or 0))
        limit = max_chars if max_chars and max_chars > 0 else BUFFER_PEEK_MAX_CHARS
        limit = min(limit, BUFFER_PEEK_MAX_CHARS)
        if safe_offset >= len(content):
            return f"Offset {safe_offset} is beyond buffer length ({len(content)} chars)."
        preview = content[safe_offset : safe_offset + limit]
        return "\n".join(
            [
                f"Buffer: {name}",
                f"Preview: offset {safe_offset}, chars {len(preview)} (max {limit})",
                "",
                preview,
            ]
        )

    @staticmethod
    def _read_buffer(
        buffer_store,
        name: str,
        offset: int,
        length: int,
        start_line: int,
        end_line: int,
    ) -> str:
        name = (name or "").strip()
        if not name:
            return "Buffer name is required for read."
        entry = buffer_store.get(name)
        if entry is None:
            return f"Buffer '{name}' not found."
        content = entry.content or ""

        if (start_line or end_line) and (offset or length):
            return "Specify either line range or offset/length, not both."

        if start_line or end_line:
            start = int(start_line or 1)
            end = int(end_line or start)
            if start < 1 or end < start:
                return "Invalid line range. Use start_line >= 1 and end_line >= start_line."
            lines = content.splitlines()
            if start > len(lines):
                return f"start_line {start} exceeds total lines ({len(lines)})."
            end = min(end, len(lines))
            slice_lines = lines[start - 1 : end]
            output = "\n".join(slice_lines)
            if len(output) > BUFFER_READ_MAX_CHARS:
                return (
                    f"Requested range is too large ({len(output)} chars). "
                    f"Max allowed is {BUFFER_READ_MAX_CHARS} chars. Narrow the range."
                )
            return "\n".join(
                [
                    f"Buffer: {name}",
                    f"Lines: {start}-{end} (total {len(lines)})",
                    "",
                    output,
                ]
            )

        safe_offset = max(0, int(offset or 0))
        safe_length = int(length or 0)
        if safe_length <= 0:
            return "Read requires length > 0 (or specify line range)."
        if safe_length > BUFFER_READ_MAX_CHARS:
            return f"Requested length {safe_length} exceeds max {BUFFER_READ_MAX_CHARS} chars."
        if safe_offset >= len(content):
            return f"Offset {safe_offset} is beyond buffer length ({len(content)} chars)."
        output = content[safe_offset : safe_offset + safe_length]
        return "\n".join(
            [
                f"Buffer: {name}",
                f"Range: offset {safe_offset}, chars {len(output)}",
                "",
                output,
            ]
        )

    @staticmethod
    def _search_buffer(buffer_store, target: str, scope: str, query: str) -> str:
        name = (scope or target or "").strip()
        if not name:
            return "Buffer name is required for search (use target or scope)."
        pattern = (query or "").strip()
        if not pattern:
            return "Search requires a regex pattern in 'query'."
        entry = buffer_store.get(name)
        if entry is None:
            return f"Buffer '{name}' not found."
        content = entry.content or ""
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return f"Invalid regex pattern: {str(exc)}"

        lines = content.splitlines()
        matches = []
        for idx, line in enumerate(lines, start=1):
            if regex.search(line):
                display_line = line
                if BUFFER_SEARCH_CONTEXT_CHARS and len(display_line) > BUFFER_SEARCH_CONTEXT_CHARS:
                    display_line = display_line[:BUFFER_SEARCH_CONTEXT_CHARS] + "…"
                matches.append(f"{name}:{idx}:{display_line}")
                if len(matches) >= BUFFER_SEARCH_MAX_MATCHES:
                    break

        if not matches:
            return f"No matches found for '{pattern}' in buffer '{name}'."

        result_lines = [f"Found {len(matches)} matches (showing up to {BUFFER_SEARCH_MAX_MATCHES}):", ""]
        result_lines.extend(matches)
        truncated = len(matches) >= BUFFER_SEARCH_MAX_MATCHES and len(lines) > len(matches)
        if truncated:
            result_lines.append("")
            result_lines.append("... results truncated. Narrow your search.")
        if BUFFER_SEARCH_CONTEXT_CHARS > 0:
            result_lines.append("")
            result_lines.append(f"Line content truncated to {BUFFER_SEARCH_CONTEXT_CHARS} chars.")
        return "\n".join(result_lines)
