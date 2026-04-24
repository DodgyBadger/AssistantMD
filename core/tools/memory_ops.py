"""
Conversation memory tool with a source-agnostic provider boundary.
"""

from __future__ import annotations

import json

from pydantic_ai import RunContext
from pydantic_ai.tools import Tool

from core.logger import UnifiedLogger
from core.memory import MemoryContext, MemoryService

from .base import BaseTool


logger = UnifiedLogger(tag="memory-ops-tool")
_MEMORY_SERVICE = MemoryService()


class MemoryOps(BaseTool):
    """Read structured conversation history for the current chat session."""

    @classmethod
    def get_tool(cls, vault_path: str | None = None):
        """Get the conversation memory tool."""

        async def memory_ops(
            ctx: RunContext,
            *,
            operation: str,
            scope: str = "session",
            session_id: str = "",
            limit: int | str = "all",
            message_filter: str = "all",
        ) -> str:
            """Read structured conversation history.

            :param operation: Operation name. Supported: "get_history", "get_tool_events".
            :param scope: History scope. Currently only "session" is supported.
            :param session_id: Optional explicit session id. Defaults to the active session when available.
            :param limit: Positive integer or "all"
            :param message_filter: For get_history only: "all", "exclude_tools", or "only_tools"
            """
            try:
                deps = getattr(ctx, "deps", None)
                requested_session_id = str(session_id or "").strip() or None
                op = (operation or "").strip().lower()
                memory_context = MemoryContext.from_deps(deps)

                logger.set_sinks(["validation"]).info(
                    "tool_invoked",
                    data={
                        "tool": "memory_ops",
                        "operation": op,
                        "scope": scope,
                    },
                )

                resolved_limit = cls._parse_limit(limit)
                if op == "get_history":
                    result = _MEMORY_SERVICE.get_conversation_history(
                        context=memory_context,
                        scope=scope,
                        session_id=requested_session_id,
                        limit=resolved_limit,
                        message_filter=message_filter,
                    )
                elif op == "get_tool_events":
                    result = _MEMORY_SERVICE.get_conversation_tool_events(
                        context=memory_context,
                        scope=scope,
                        session_id=requested_session_id,
                        limit=resolved_limit,
                    )
                else:
                    return "Unknown operation. Available: get_history, get_tool_events"
                return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "memory_ops failed",
                    data={
                        "operation": operation,
                        "scope": scope,
                        "session_id": session_id,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
                return f"Error performing '{operation}' operation: {exc}"

        return Tool(
            memory_ops,
            name="memory_ops",
            description="Read structured conversation history through a source-agnostic memory provider.",
        )

    @classmethod
    def get_instructions(cls) -> str:
        """Get usage instructions for conversation memory access."""
        return """
Read structured conversation history through a source-agnostic memory provider.

Important notes:
- use `operation="get_history"` to read conversation history
- `get_history` is the primary agent-facing operation over canonical ordered message history
- `get_history` supports `message_filter="all" | "exclude_tools" | "only_tools"`
- use `operation="get_tool_events"` only for explicit inspection/debug retrieval of structured tool activity
- default `scope="session"` reads the active chat session when available
"""

    @staticmethod
    def _parse_limit(value: int | str) -> int | str:
        if isinstance(value, int):
            if value <= 0:
                raise ValueError("limit must be a positive integer or 'all'")
            return value
        normalized = str(value or "").strip().lower()
        if not normalized or normalized == "all":
            return "all"
        if normalized.isdigit():
            parsed = int(normalized)
            if parsed <= 0:
                raise ValueError("limit must be a positive integer or 'all'")
            return parsed
        raise ValueError("limit must be a positive integer or 'all'")
