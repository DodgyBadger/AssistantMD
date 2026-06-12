"""Experiment probe for live-model repeated compaction summary quality.

This scenario intentionally uses the real compaction summarizer. Keep it in
experiments so normal integration runs do not depend on live model behavior.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from validation.core.base_scenario import BaseScenario


class RepeatedCompactionLiveProbeScenario(BaseScenario):
    """Probe whether live repeated compaction preserves recovery-card semantics."""

    async def test_scenario(self):
        vault = self.create_vault("RepeatedCompactionLiveProbeVault")

        await self.start_system()

        import core.chat.compaction as compaction
        from core.chat.chat_store import ChatStore
        from core.runtime.state import get_runtime_context

        runtime = get_runtime_context()
        store = ChatStore(system_root=str(runtime.config.system_root))
        session_id = "repeated_compaction_live_probe_session"
        store.add_messages(
            session_id,
            vault.name,
            [
                _user("Objective: prepare the Meridian donor briefing."),
                ModelResponse(parts=[TextPart(content="Progress: drafted the briefing outline.")]),
                _user("Constraint: include caveats about missing Q4 figures."),
                _assistant("Next step: collect updated donor metrics."),
            ],
        )

        original_keep_recent = compaction.get_compaction_keep_recent
        compaction.get_compaction_keep_recent = lambda: 1
        try:
            first = await compaction.compact_chat_history(
                session_id=session_id,
                vault_name=vault.name,
                vault_path=str(vault),
                focus=(
                    "Preserve objective, progress, constraints, caveats, blockers, "
                    "and the next action as a recovery card."
                ),
            )
            store.add_messages(
                session_id,
                vault.name,
                [
                    _user("Update: donor metrics are now collected."),
                    _assistant(
                        "Superseding update: Q4 figures arrived; "
                        "remove the missing-figures caveat."
                    ),
                ],
            )
            second = await compaction.compact_chat_history(
                session_id=session_id,
                vault_name=vault.name,
                vault_path=str(vault),
                focus=(
                    "Merge the previous recovery card with newer updates. "
                    "Remove stale missing-Q4 caveats because Q4 figures arrived."
                ),
            )
        finally:
            compaction.get_compaction_keep_recent = original_keep_recent

        effective_messages = store.get_stored_messages(session_id, vault.name)
        assert len(effective_messages) == 2, (
            "Repeated live compaction should keep effective history compact"
        )
        summary = effective_messages[0].content_text.lower()

        assert first.status == "completed", "First live compaction should complete"
        assert second.status == "completed", "Second live compaction should complete"
        assert "meridian" in summary, "Latest card should preserve the named briefing target"
        assert "donor" in summary, "Latest card should preserve the domain"
        assert "metrics" in summary or "figures" in summary, (
            "Latest card should preserve the updated evidence state"
        )
        assert "missing q4" not in summary and "missing-q4" not in summary, (
            "Latest card should not retain the explicitly superseded missing-Q4 caveat"
        )
        assert "next" in summary or "step" in summary, (
            "Latest card should preserve a continuation cue"
        )

        (self.artifacts_dir / "latest_compaction_card.md").write_text(
            effective_messages[0].content_text,
            encoding="utf-8",
        )

        await self.stop_system()
        self.teardown_scenario()


def _user(content: str) -> ModelRequest:
    return ModelRequest(parts=[UserPromptPart(content=content)])


def _assistant(content: str) -> ModelResponse:
    return ModelResponse(parts=[TextPart(content=content)])
