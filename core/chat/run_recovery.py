"""Harness-backed recovery state for one primary chat execution task."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
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
    interrupted: bool = False


class ChatRecoveryStrategy(StrEnum):
    """Coordinator outcomes for a retryable failed agent run."""

    RESUME_SNAPSHOT = "resume_snapshot"
    REPLAY_NO_EFFECT = "replay_no_effect"
    TERMINAL_ROLLBACK_RESTART = "terminal_rollback_restart"
    MANUAL_REQUIRED = "manual_required"


@dataclass(frozen=True)
class ChatRecoveryDecision:
    """One recovery strategy selected from snapshot and tool-effect state."""

    strategy: ChatRecoveryStrategy
    reason: str
    checkpoint: ChatRecoveryCheckpoint | None = None
    completed_tool_count: int = 0
    unresolved_tool_count: int = 0


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
        """Select a safe settled continuation point from the latest failed run."""
        decision = await self.decide(conversation_id=conversation_id)
        if decision.strategy is not ChatRecoveryStrategy.RESUME_SNAPSHOT:
            return None
        return decision.checkpoint

    async def decide(self, *, conversation_id: str) -> ChatRecoveryDecision:
        """Choose recovery from Harness state and developer-declared tool policy.

        Harness captures live history on failure. If a failed streaming model
        request appended a partial response, remove only that trailing response;
        the preceding settled tool-return request remains the continuation point.
        """
        runs = await self.store.list_runs(conversation_id=conversation_id)
        if not runs:
            return ChatRecoveryDecision(
                strategy=ChatRecoveryStrategy.MANUAL_REQUIRED,
                reason="run_missing",
            )
        run = runs[-1]
        events = await self.store.list_events(run_id=run.run_id)
        if not events or events[-1].kind != "run_failed":
            return ChatRecoveryDecision(
                strategy=ChatRecoveryStrategy.MANUAL_REQUIRED,
                reason="run_not_failed",
            )
        completed_tool_count = sum(
            event.kind == "tool_call_completed" for event in events
        )
        unresolved = await self.store.list_unresolved_tool_effects(run_id=run.run_id)
        if unresolved:
            policies = {self.tool_policy(effect.tool_name) for effect in unresolved}
            if policies == {ToolRecoveryPolicy.REPLAY_SAFE}:
                snapshot = await self.store.latest_snapshot(
                    run_id=run.run_id,
                    include_interrupted=True,
                )
                if snapshot is None:
                    return ChatRecoveryDecision(
                        strategy=ChatRecoveryStrategy.MANUAL_REQUIRED,
                        reason="snapshot_missing",
                        completed_tool_count=completed_tool_count,
                        unresolved_tool_count=len(unresolved),
                    )
                return ChatRecoveryDecision(
                    strategy=ChatRecoveryStrategy.REPLAY_NO_EFFECT,
                    reason="unresolved_replay_safe_effect",
                    checkpoint=ChatRecoveryCheckpoint(
                        run_id=run.run_id,
                        step_index=snapshot.step_index,
                        messages=list(snapshot.messages),
                        trimmed_failed_response=False,
                        interrupted=snapshot.state == "interrupted",
                    ),
                    completed_tool_count=completed_tool_count,
                    unresolved_tool_count=len(unresolved),
                )
            if ToolRecoveryPolicy.VAULT_TRANSACTIONAL in policies:
                return ChatRecoveryDecision(
                    strategy=ChatRecoveryStrategy.TERMINAL_ROLLBACK_RESTART,
                    reason="unresolved_vault_effect",
                    completed_tool_count=completed_tool_count,
                    unresolved_tool_count=len(unresolved),
                )
            return ChatRecoveryDecision(
                strategy=ChatRecoveryStrategy.MANUAL_REQUIRED,
                reason="unresolved_external_or_unknown_effect",
                completed_tool_count=completed_tool_count,
                unresolved_tool_count=len(unresolved),
            )

        snapshot = await self.store.latest_snapshot(run_id=run.run_id)
        if snapshot is None:
            return ChatRecoveryDecision(
                strategy=ChatRecoveryStrategy.MANUAL_REQUIRED,
                reason="snapshot_missing",
                completed_tool_count=completed_tool_count,
            )
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
            return ChatRecoveryDecision(
                strategy=ChatRecoveryStrategy.MANUAL_REQUIRED,
                reason="snapshot_invalid",
                completed_tool_count=completed_tool_count,
            )
        return ChatRecoveryDecision(
            strategy=ChatRecoveryStrategy.RESUME_SNAPSHOT,
            reason="settled_checkpoint",
            checkpoint=ChatRecoveryCheckpoint(
                run_id=run.run_id,
                step_index=snapshot.step_index,
                messages=messages,
                trimmed_failed_response=trimmed_failed_response,
            ),
            completed_tool_count=completed_tool_count,
        )
