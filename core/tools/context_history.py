"""
Context history tool for the context compiler.

Exposes recent compiled summaries and micro-log entries so the compiler can
reconcile objectives, constraints, and detours without pulling full transcripts.
"""

from typing import Any

from pydantic import Field
from pydantic_ai import RunContext

from .base import BaseTool
from core.context.store import (
    get_recent_micro_log,
    get_recent_summaries,
    get_summary_by_id,
)


class ContextHistoryTool(BaseTool):
    """Provide access to recent compiled context snapshots."""

    @classmethod
    def get_tool(
        cls,
        *,
        session_id: str,
        vault_name: str,
        default_limit: int = 5,
    ):
        """Return a tool function bound to a specific chat session."""

        async def get_recent_snapshots(
            ctx: RunContext,
            limit: int = Field(
                default=default_limit,
                ge=1,
                le=10,
                description="How many recent micro-log entries to fetch (max 10).",
            ),
            summary_id: int | None = Field(
                default=None,
                description="Optional: fetch a specific compiled summary by id instead of recent entries.",
            ),
        ) -> dict[str, Any]:
            """
            Fetch recent micro-log entries or a specific compiled summary.

            Returns:
                If summary_id is provided:
                  { "summary": {...} } with parsed/raw/compiled_prompt/input_payload/canonical_topic
                Else:
                  {
                    "micro_log": [
                      {
                        "id", "turn_index", "summary_id", "canonical_topic",
                        "stable_count", "user_input_snippet", "embedding", "created_at"
                      }, ...
                    ],
                    "snapshots": [ ...compiled summaries... with canonical_topic ]
                  }
            """
            if summary_id is not None:
                summary = get_summary_by_id(summary_id)
                return {"summary": summary}

            micro_log = get_recent_micro_log(
                session_id=session_id,
                vault_name=vault_name,
                limit=limit,
            )

            snapshots = get_recent_summaries(
                session_id=session_id,
                vault_name=vault_name,
                limit=limit,
            )
            return {"micro_log": micro_log, "snapshots": snapshots}

        return get_recent_snapshots

    @classmethod
    def get_instructions(cls) -> str:
        """Explain usage for the context history tool."""
        return (
            "context_history: Fetch recent micro-log entries (canonical_topic, stable_count, summary_id, optional embedding) "
            "or a specific compiled summary by id. Use it to reconcile anchors, revisit a past view, "
            "or detect when you returned to a previous state."
        )
