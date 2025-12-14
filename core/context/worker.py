"""
Background worker to backfill micro-log entries and optional embeddings for compiled context summaries.
"""

from __future__ import annotations

import asyncio
import json
from typing import Optional

from core.context.store import (
    add_micro_log_entry,
    fetch_summaries_without_micro_log,
    update_canonical_topic,
)
from core.llm.agents import create_agent
from core.logger import UnifiedLogger
from core.constants import CANONICAL_TOPIC_INSTRUCTIONS


class ContextMicroLogWorker:
    """
    Periodically backfill micro-log entries for compiled context summaries.

    Responsibilities:
    - Populate canonical_topic when missing.
    - Insert micro-log entries for summaries that don't have one.
    - (Future) Compute embeddings for canonical_topic when configured.
    """

    def __init__(self, batch_size: int = 50, model_alias: Optional[str] = None):
        self.batch_size = batch_size
        self.model_alias = model_alias
        self.logger = UnifiedLogger(tag="context-micro-log")

    async def run_once(self) -> None:
        try:
            await self._process_batch()
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.error("Context micro-log worker failed", metadata={"error": str(exc)})

    async def _process_batch(self) -> None:
        if not self.model_alias:
            self.logger.info("Context micro-log disabled: no model configured")
            return

        pending = await asyncio.to_thread(fetch_summaries_without_micro_log, limit=self.batch_size)
        if not pending:
            return

        for summary in pending:
            try:
                canonical_topic = summary.get("canonical_topic")
                if not canonical_topic:
                    canonical_topic = await self._generate_canonical_topic(summary)
                    await asyncio.to_thread(update_canonical_topic, summary["id"], canonical_topic)

                embedding = None  # Optional future: compute embedding for canonical_topic

                await asyncio.to_thread(
                    add_micro_log_entry,
                    summary["session_id"],
                    summary["vault_name"],
                    summary.get("turn_index"),
                    summary["id"],
                    _safe_latest_input(summary.get("input_payload")),
                    canonical_topic,
                    embedding,
                )
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.warning(
                    "Failed to process summary for micro-log",
                    metadata={"summary_id": summary.get("id"), "error": str(exc)},
                )

    async def _generate_canonical_topic(self, summary: dict) -> Optional[str]:
        """
        Generate a concise canonical topic via model using the compiled summary content.

        Falls back to latest input snippet if model generation fails.
        """
        summary_json = summary.get("summary_json")
        compiled_prompt = summary.get("compiled_prompt") or ""
        raw_output = summary.get("raw_output") or ""
        latest_input = _safe_latest_input(summary.get("input_payload"))

        # Simple prompt assembly to keep it deterministic and short
        prompt_parts = [
            "You are extracting a canonical topic for a chat session.",
            "Return one short phrase (<=120 characters) capturing the current objective/topic.",
            "Be terse, no quotes, no numbering.",
            "",
            "Compiled summary JSON:",
            json.dumps(summary_json, ensure_ascii=False) if summary_json is not None else "N/A",
        ]
        if compiled_prompt:
            prompt_parts.extend(["", "Compiled prompt:", compiled_prompt[:800]])
        if raw_output:
            prompt_parts.extend(["", "Raw output:", raw_output[:800]])
        if latest_input:
            prompt_parts.extend(["", "Latest input:", latest_input])

        prompt = "\n".join(prompt_parts)

        try:
            agent = await create_agent(
                instructions=CANONICAL_TOPIC_INSTRUCTIONS,
                output_type=str,
                model=self.model_alias,
            )
            result = await asyncio.wait_for(agent.run(prompt), timeout=5)
            topic = (result.output or "").strip()
            if topic:
                return topic[:200]
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.warning(
                "Canonical topic generation failed, using fallback",
                metadata={"summary_id": summary.get("id"), "error": str(exc)},
            )

        return latest_input


def _safe_latest_input(input_payload: Optional[dict]) -> Optional[str]:
    if not isinstance(input_payload, dict):
        return None
    latest = input_payload.get("latest_input")
    return str(latest)[:400] if latest else None
