"""
Integration scenario for the chat-facing memory_ops tool.

Validates that a selected chat agent can call memory_ops through the normal
tool path and use active chat session/vault context for work episode operations.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation.core.base_scenario import BaseScenario


class MemoryOpsChatToolScenario(BaseScenario):
    """Validate memory_ops can link and update work episodes from chat."""

    async def test_scenario(self):
        vault = self.create_vault("MemoryOpsChatToolVault")
        session_id = "memory_ops_chat_tool_session"
        episode_id = "episode-chat-tool-probe"

        await self.start_system()

        import core.chat.executor as chat_executor
        from core.authoring.shared.tool_binding import resolve_tool_binding
        from core.memory.work_episodes import WorkEpisodeStore
        from pydantic_ai.models.test import TestModel

        store = WorkEpisodeStore(system_root=str(self._get_system_controller()._system_root))
        store.create_episode(
            episode_id=episode_id,
            vault_name=vault.name,
            title="Chat tool memory probe",
            confidence=0.9,
            metadata={"origin": "validation"},
        )

        current_case = {"name": "link"}

        class _MemoryOpsToolModel(TestModel):
            def __init__(self):
                super().__init__(call_tools=["memory_ops"])

            def gen_tool_args(self, tool_def):
                if getattr(tool_def, "name", "") != "memory_ops":
                    return super().gen_tool_args(tool_def)
                if current_case["name"] == "link":
                    return {
                        "operation": "link_session",
                        "episode_id": episode_id,
                        "link_source": "validation_chat",
                        "confidence": 0.93,
                    }
                if current_case["name"] == "update":
                    return {
                        "operation": "update_episode",
                        "episode_id": episode_id,
                        "field_type": "topic",
                        "value": "chat memory testing",
                        "confidence": 0.71,
                    }
                raise AssertionError(f"Unexpected memory_ops case: {current_case['name']}")

        def _patched_prepare_agent_config(vault_name, vault_path, tools, model, thinking=None):
            del vault_name, tools, model, thinking
            binding = resolve_tool_binding(["memory_ops"], vault_path=vault_path)
            return (
                "You must call memory_ops before responding.",
                binding.tool_instructions,
                _MemoryOpsToolModel(),
                binding.tool_functions,
            )

        original_prepare = chat_executor._prepare_agent_config
        chat_executor._prepare_agent_config = _patched_prepare_agent_config
        try:
            linked = self.call_api(
                "/api/chat/execute",
                method="POST",
                data={
                    "vault_name": vault.name,
                    "prompt": "Link this chat to the seeded work episode.",
                    "session_id": session_id,
                    "tools": ["memory_ops"],
                    "model": "test",
                },
            )
            self.soft_assert_equal(linked.status_code, 200, "Link chat should succeed")
            current = store.get_current_episode(vault_name=vault.name, session_id=session_id)
            self.soft_assert(
                current is not None and current.episode_id == episode_id,
                "memory_ops should link the active chat session to the seeded episode",
            )

            current_case["name"] = "update"
            updated = self.call_api(
                "/api/chat/execute",
                method="POST",
                data={
                    "vault_name": vault.name,
                    "prompt": "Update the current work episode topic.",
                    "session_id": f"{session_id}_update",
                    "tools": ["memory_ops"],
                    "model": "test",
                },
            )
            self.soft_assert_equal(updated.status_code, 200, "Update chat should succeed")
            episode = store.get_episode(episode_id)
            self.soft_assert(
                episode is not None
                and _has_field(episode.fields, "topic", "chat memory testing"),
                "memory_ops should update episode fields from chat",
            )
        finally:
            chat_executor._prepare_agent_config = original_prepare
            await self.stop_system()
            self.teardown_scenario()

        self.assert_no_failures()


def _has_field(fields: tuple[object, ...], field_type: str, normalized_value: str) -> bool:
    return any(
        getattr(field, "field_type", None) == field_type
        and getattr(field, "normalized_value", None) == normalized_value
        for field in fields
    )
