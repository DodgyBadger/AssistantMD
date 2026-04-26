"""
Integration scenario validating same-session multi-pass local exploration in chat.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation.core.base_scenario import BaseScenario


class ChatCacheMultiPassScenario(BaseScenario):
    """Validate one local artifact can be revisited across multiple chat turns."""

    async def test_scenario(self):
        vault = self.create_vault("ChatCacheMultiPassVault")
        self.create_file(vault, "notes/repeated.md", "OVERFLOW_SEGMENT " * 1200)

        await self.start_system()

        import core.chat.executor as chat_executor
        from core.authoring.shared.tool_binding import resolve_tool_binding
        from core.logger import UnifiedLogger
        from pydantic_ai.models.test import TestModel

        session_id = "chat_cache_multi_pass_session"
        tool_logger = UnifiedLogger(tag="chat-cache-multi-pass-tool")
        call_index = {"value": 0}

        async def overflow_probe() -> str:
            tool_logger.set_sinks(["validation"]).info(
                "tool_invoked",
                data={"tool": "overflow_probe"},
            )
            return "OVERFLOW_SEGMENT " * 1200

        class _DeterministicToolModel(TestModel):
            def __init__(self, call_tools):
                super().__init__(call_tools=call_tools)

            def gen_tool_args(self, tool_def):
                name = getattr(tool_def, "name", "")
                if name != "code_execution_local":
                    return super().gen_tool_args(tool_def)
                if call_index["value"] == 2:
                    return {
                        "code": (
                            'artifact = await file_ops_safe(operation="read", path="notes/repeated.md")\n'
                            'text = artifact.output.split("\\n\\n", 1)[1] if "\\n\\n" in artifact.output else artifact.output\n'
                            "text[:80]"
                        )
                    }
                if call_index["value"] == 3:
                    return {
                        "code": (
                            'artifact = await file_ops_safe(operation="read", path="notes/repeated.md")\n'
                            'text = artifact.output.split("\\n\\n", 1)[1] if "\\n\\n" in artifact.output else artifact.output\n'
                            'str(text.count("OVERFLOW_SEGMENT"))'
                        )
                    }
                raise AssertionError("Unexpected code_execution_local phase")

        def _patched_prepare_agent_config(vault_name, vault_path, tools, model, thinking=None):
            del vault_name, tools, model, thinking
            call_index["value"] += 1
            binding = resolve_tool_binding(
                ["code_execution_local"],
                vault_path=vault_path,
            )
            if call_index["value"] == 1:
                return (
                    "You must call overflow_probe before responding.",
                    "",
                    _DeterministicToolModel(["overflow_probe"]),
                    [overflow_probe],
                )
            if call_index["value"] in {2, 3}:
                return (
                    "You must call code_execution_local before responding.",
                    binding.tool_instructions,
                    _DeterministicToolModel(["code_execution_local"]),
                    binding.tool_functions,
                )
            raise AssertionError("Unexpected chat call count")

        def _passthrough_history_processor(**kwargs):
            async def processor(messages):
                return messages
            return processor

        original_prepare_agent_config = chat_executor._prepare_agent_config
        original_get_history = chat_executor._CHAT_STORE.get_history
        original_build_history_processor = chat_executor.build_context_manager_history_processor
        chat_executor._prepare_agent_config = _patched_prepare_agent_config
        chat_executor._CHAT_STORE.get_history = lambda _sid, _vault: None
        chat_executor.build_context_manager_history_processor = _passthrough_history_processor
        try:
            update_setting = self.call_api(
                "/api/system/settings/general/auto_cache_max_tokens",
                method="PUT",
                data={"value": "50"},
            )
            assert update_setting.status_code == 200, "Scenario should lower chat overflow threshold"

            checkpoint = self.event_checkpoint()

            first = self.call_api(
                "/api/chat/execute",
                method="POST",
                data={
                    "vault_name": vault.name,
                    "prompt": "Use overflow_probe and then answer briefly.",
                    "session_id": session_id,
                    "tools": ["overflow_probe"],
                    "model": "test",
                },
            )
            assert first.status_code == 200, "Initial oversized tool call should succeed"

            second = self.call_api(
                "/api/chat/execute",
                method="POST",
                data={
                    "vault_name": vault.name,
                    "prompt": "Inspect the repeated note and show the beginning.",
                    "session_id": session_id,
                    "tools": ["code_execution_local", "file_ops_safe"],
                    "model": "test",
                },
            )
            assert second.status_code == 200, "First local exploration pass should succeed"
            second_text = second.json()["response"]
            self.soft_assert(
                "OVERFLOW_SEGMENT" in second_text,
                "First local exploration pass should read the repeated note content",
            )

            third = self.call_api(
                "/api/chat/execute",
                method="POST",
                data={
                    "vault_name": vault.name,
                    "prompt": "Inspect the same repeated note again and count the repeated token.",
                    "session_id": session_id,
                    "tools": ["code_execution_local", "file_ops_safe"],
                    "model": "test",
                },
            )
            assert third.status_code == 200, "Second local exploration pass should succeed"
            third_text = third.json()["response"]
            self.soft_assert(
                "1200" in third_text,
                "Second local exploration pass should revisit the same note and compute a deterministic result",
            )

            events = self.events_since(checkpoint)
            overflow_events = self.find_events(events, name="tool_invoked", tool="overflow_probe")
            local_events = self.find_events(events, name="tool_invoked", tool="code_execution_local")
            self.soft_assert_equal(
                len(overflow_events),
                1,
                "Original oversized tool should run exactly once across multi-pass exploration",
            )
            self.soft_assert_equal(
                len(local_events),
                2,
                "code_execution_local should handle the two later exploration passes",
            )
        finally:
            chat_executor._prepare_agent_config = original_prepare_agent_config
            chat_executor._CHAT_STORE.get_history = original_get_history
            chat_executor.build_context_manager_history_processor = original_build_history_processor
            await self.stop_system()
            self.teardown_scenario()
