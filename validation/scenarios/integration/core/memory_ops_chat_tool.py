"""
Integration scenario for the chat-facing memory_ops tool.

Validates that a selected chat agent can call memory_ops through the normal
tool path and use active chat session/vault context for workstream operations.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation.core.base_scenario import BaseScenario


class MemoryOpsChatToolScenario(BaseScenario):
    """Validate memory_ops can link and update workstreams from chat."""

    async def test_scenario(self):
        vault = self.create_vault("MemoryOpsChatToolVault")
        session_id = "memory_ops_chat_tool_session"
        workstream_id = "workstream-chat-tool-probe"

        await self.start_system()

        import core.chat.executor as chat_executor
        from core.authoring.shared.tool_binding import resolve_tool_binding
        from core.memory.workstreams import WorkstreamStore
        from pydantic_ai.models.test import TestModel

        store = WorkstreamStore(system_root=str(self._get_system_controller()._system_root))
        store.create_workstream(
            workstream_id=workstream_id,
            vault_name=vault.name,
            title="Chat tool memory probe",
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
                        "workstream_id": workstream_id,
                    }
                if current_case["name"] == "update":
                    return {
                        "operation": "update_workstream",
                        "workstream_id": workstream_id,
                        "topic": "chat memory testing",
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
                    "prompt": "Link this chat to the seeded workstream.",
                    "session_id": session_id,
                    "tools": ["memory_ops"],
                    "model": "test",
                },
            )
            self.soft_assert_equal(linked.status_code, 200, "Link chat should succeed")
            current = store.get_current_workstream(vault_name=vault.name, session_id=session_id)
            self.soft_assert(
                current is not None and current.workstream_id == workstream_id,
                "memory_ops should link the active chat session to the seeded workstream",
            )

            current_case["name"] = "update"
            updated = self.call_api(
                "/api/chat/execute",
                method="POST",
                data={
                    "vault_name": vault.name,
                    "prompt": "Update the current workstream topic.",
                    "session_id": f"{session_id}_update",
                    "tools": ["memory_ops"],
                    "model": "test",
                },
            )
            self.soft_assert_equal(updated.status_code, 200, "Update chat should succeed")
            workstream = store.get_workstream(workstream_id)
            self.soft_assert(
                workstream is not None
                and workstream.topic == "chat memory testing",
                "memory_ops should update direct workstream fields from chat",
            )
        finally:
            chat_executor._prepare_agent_config = original_prepare
            await self.stop_system()
            self.teardown_scenario()

        self.assert_no_failures()
