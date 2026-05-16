"""
Integration scenario for the chat-facing memory_ops tool.

Validates that a selected chat agent can call memory_ops through the normal
tool path and use active chat session/vault context for session memory.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation.core.base_scenario import BaseScenario


class MemoryOpsChatToolScenario(BaseScenario):
    """Validate memory_ops can write and read session memory from chat."""

    async def test_scenario(self):
        vault = self.create_vault("MemoryOpsChatToolVault")
        session_id = "memory_ops_chat_tool_session"

        await self.start_system()

        import core.chat.executor as chat_executor
        from core.authoring.shared.tool_binding import resolve_tool_binding
        from core.memory.session_memory import SessionMemoryStore
        from pydantic_ai.models.test import TestModel

        store = SessionMemoryStore(system_root=str(self._get_system_controller()._system_root))

        current_case = {"name": "upsert"}

        class _MemoryOpsToolModel(TestModel):
            def __init__(self):
                super().__init__(call_tools=["memory_ops"])

            def gen_tool_args(self, tool_def):
                if getattr(tool_def, "name", "") != "memory_ops":
                    return super().gen_tool_args(tool_def)
                if current_case["name"] == "upsert":
                    return {
                        "operation": "upsert_session_memory",
                        "data": {
                            "summary": "Chat memory testing",
                            "domain": "validation",
                            "work_product": "test artifact",
                            "user_intent": "Validate that chat can write session memory.",
                        },
                    }
                if current_case["name"] == "get":
                    return {"operation": "get_session_memory"}
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
            upserted = self.call_api(
                "/api/chat/execute",
                method="POST",
                data={
                    "vault_name": vault.name,
                    "prompt": "Write memory for this chat session.",
                    "session_id": session_id,
                    "tools": ["memory_ops"],
                    "model": "test",
                },
            )
            self.soft_assert_equal(upserted.status_code, 200, "Memory chat should succeed")
            current = store.get_session_memory(vault_name=vault.name, session_id=session_id)
            self.soft_assert(
                current is not None and current.summary == "Chat memory testing",
                "memory_ops should write memory for the active chat session",
            )

            current_case["name"] = "get"
            fetched = self.call_api(
                "/api/chat/execute",
                method="POST",
                data={
                    "vault_name": vault.name,
                    "prompt": "Fetch the current session memory.",
                    "session_id": session_id,
                    "tools": ["memory_ops"],
                    "model": "test",
                },
            )
            self.soft_assert_equal(fetched.status_code, 200, "Fetch chat should succeed")

            deleted = self.call_api(
                f"/api/chat/sessions/{session_id}",
                method="DELETE",
                params={"vault_name": vault.name},
            )
            self.soft_assert_equal(deleted.status_code, 200, "Delete chat should succeed")
            after_delete = store.get_session_memory(vault_name=vault.name, session_id=session_id)
            self.soft_assert(
                after_delete is None,
                "Deleting a chat session should delete the matching session memory",
            )
        finally:
            chat_executor._prepare_agent_config = original_prepare
            await self.stop_system()
            self.teardown_scenario()

        self.assert_no_failures()
