"""Chat-visible tool for current-session history compaction."""

from __future__ import annotations

import json

from pydantic_ai import RunContext
from pydantic_ai.tools import Tool

from core.chat.compaction import compact_chat_history, get_compaction_status
from core.logger import UnifiedLogger
from core.runtime.execution_tasks import (
    ExecutionTaskKind,
    ExecutionTaskSource,
    chat_session_scope,
    compaction_task_label,
)
from core.runtime.state import get_runtime_context

from .base import BaseTool


logger = UnifiedLogger(tag="chat-history-compact-tool")


class ChatHistoryCompact(BaseTool):
    """Check or compact the active chat session history."""

    @classmethod
    def get_tool(cls, vault_path: str | None = None):
        """Get the chat history compaction tool."""

        async def chat_history_compact(
            ctx: RunContext,
            *,
            operation: str = "status",
            focus: str = "",
            export_before: bool | None = None,
        ) -> str:
            """Check or compact the current chat session history.

            :param operation: status or compact
            :param focus: Optional user instructions for what the summary should preserve
            :param export_before: Optional override for transcript export before compaction
            """
            deps = getattr(ctx, "deps", None)
            session_id = str(getattr(deps, "session_id", "") or "").strip()
            vault_name = str(getattr(deps, "vault_name", "") or "").strip()
            if not session_id or not vault_name:
                return "chat_history_compact requires active chat session context."

            normalized_operation = (operation or "status").strip().lower()
            if normalized_operation == "status":
                status = await get_compaction_status(
                    session_id=session_id,
                    vault_name=vault_name,
                )
                return json.dumps(status.__dict__, ensure_ascii=False, sort_keys=True)
            if normalized_operation != "compact":
                return "operation must be either 'status' or 'compact'."

            runtime = get_runtime_context()
            effective_vault_path = vault_path or str(runtime.config.data_root / vault_name)
            logger.info(
                "tool_invoked",
                data={"tool": "chat_history_compact", "operation": "compact"},
            )
            async with runtime.task_coordinator.track_current_task(
                kind=ExecutionTaskKind.HISTORY_COMPACTION,
                scope=chat_session_scope(session_id),
                source=ExecutionTaskSource.TOOL,
                label=compaction_task_label(session_id),
                metadata={"vault": vault_name, "session_id": session_id},
            ):
                result = await compact_chat_history(
                    session_id=session_id,
                    vault_name=vault_name,
                    vault_path=effective_vault_path,
                    focus=focus or None,
                    export_before=export_before,
                    source=ExecutionTaskSource.TOOL,
                )
            return json.dumps(result.as_tool_dict(), ensure_ascii=False, sort_keys=True)

        return Tool(
            chat_history_compact,
            name="chat_history_compact",
            description="Check or compact the current chat session history after explicit user approval.",
        )

    @classmethod
    def get_instructions(cls) -> str:
        """Get usage instructions for chat history compaction."""
        return """
Full documentation:
- `__virtual_docs__/tools/chat_history_compact.md`
"""
