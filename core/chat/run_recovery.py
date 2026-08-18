"""Harness-backed recovery state for one primary chat execution task."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai_harness.step_persistence import (
    InMemoryStepStore,
    StepPersistence,
    is_provider_valid,
)

from core.tools.base import ToolRecoveryPolicy


@dataclass(frozen=True)
class ChatRecoveryCheckpoint:
    """A settled provider-valid boundary selected for automatic continuation."""

    run_id: str
    step_index: int
    messages: list[ModelMessage]
    trimmed_failed_response: bool


class ChatRunRecoveryCoordinator:
    """Own Harness recovery state for the lifetime of one logical chat task."""

    def __init__(
        self, *, tool_policies: dict[str, ToolRecoveryPolicy] | None = None
    ) -> None:
        self.store = InMemoryStepStore()
        self.tool_policies = dict(tool_policies or {})

    @classmethod
    def from_tools(cls, tools: list[Any]) -> ChatRunRecoveryCoordinator:
        """Build recovery policy lookup from resolved Pydantic tool metadata."""
        policies: dict[str, ToolRecoveryPolicy] = {}
        for tool in tools:
            name = str(getattr(tool, "name", "") or "").strip()
            metadata = getattr(tool, "metadata", None)
            assistantmd = (
                metadata.get("assistantmd") if isinstance(metadata, dict) else None
            )
            raw_policy = (
                assistantmd.get("recovery_policy")
                if isinstance(assistantmd, dict)
                else None
            )
            if not name:
                continue
            if not isinstance(raw_policy, str):
                policies[name] = ToolRecoveryPolicy.UNKNOWN
                continue
            try:
                policies[name] = ToolRecoveryPolicy(raw_policy)
            except ValueError:
                policies[name] = ToolRecoveryPolicy.UNKNOWN
        return cls(tool_policies=policies)

    def tool_policy(self, tool_name: str) -> ToolRecoveryPolicy:
        """Return the declared policy or the fail-closed default."""
        return self.tool_policies.get(tool_name, ToolRecoveryPolicy.UNKNOWN)

    def capability(self, *, session_id: str) -> StepPersistence:
        """Build the Harness capability that records this task's run attempts."""
        return StepPersistence(
            store=self.store,
            agent_name="primary-chat",
            metadata={"session_id": session_id},
        )

    async def select_settled_checkpoint(
        self, *, conversation_id: str
    ) -> ChatRecoveryCheckpoint | None:
        """Select a safe continuation point from the latest failed run.

        Harness captures live history on failure. If a failed streaming model
        request appended a partial response, remove only that trailing response;
        the preceding settled tool-return request remains the continuation point.
        """
        runs = await self.store.list_runs(conversation_id=conversation_id)
        if not runs:
            return None
        run = runs[-1]
        events = await self.store.list_events(run_id=run.run_id)
        if not events or events[-1].kind != "run_failed":
            return None
        if await self.store.list_unresolved_tool_effects(run_id=run.run_id):
            return None

        snapshot = await self.store.latest_snapshot(run_id=run.run_id)
        if snapshot is None:
            return None
        messages = list(snapshot.messages)
        trimmed_failed_response = bool(
            messages
            and isinstance(messages[-1], ModelResponse)
            and any(
                getattr(part, "part_kind", None) in {"text", "thinking"}
                for part in messages[-1].parts
            )
        )
        if trimmed_failed_response:
            messages.pop()
        if not messages or not is_provider_valid(messages):
            return None
        return ChatRecoveryCheckpoint(
            run_id=run.run_id,
            step_index=snapshot.step_index,
            messages=messages,
            trimmed_failed_response=trimmed_failed_response,
        )
