"""
Integration scenario validating same-session multi-pass cache exploration in chat.
"""

import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation.core.base_scenario import BaseScenario


class ChatCacheMultiPassScenario(BaseScenario):
    """Validate one cached artifact can be revisited across multiple chat turns."""

    async def test_scenario(self):
        vault = self.create_vault("ChatCacheMultiPassVault")

        await self.start_system()

        import api.endpoints as api_endpoints
        import core.llm.chat_executor as chat_executor
        from core.authoring.shared.tool_binding import resolve_tool_binding
        from core.context.store import get_cache_artifact
        from core.logger import UnifiedLogger
        from core.runtime.state import get_runtime_context
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
                cache_ref = "tool/overflow_probe/pyd_ai_tool_call_id__overflow_probe"
                if call_index["value"] == 2:
                    return {
                        "code": (
                            f'artifact = await retrieve(type="cache", ref="{cache_ref}")\n'
                            "artifact.items[0].content[:80]"
                        )
                    }
                if call_index["value"] == 3:
                    return {
                        "code": (
                            f'artifact = await retrieve(type="cache", ref="{cache_ref}")\n'
                            'str(artifact.items[0].content.count("OVERFLOW_SEGMENT"))'
                        )
                    }
                raise AssertionError("Unexpected code_execution_local phase")

        def _patched_prepare_agent_config(vault_name, vault_path, tools, model):
            del vault_name, tools, model
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

        original_prepare_agent_config = chat_executor._prepare_agent_config
        original_get_history = api_endpoints.session_manager.get_history
        chat_executor._prepare_agent_config = _patched_prepare_agent_config
        api_endpoints.session_manager.get_history = lambda _sid, _vault: None
        try:
            update_setting = self.call_api(
                "/api/system/settings/general/auto_buffer_max_tokens",
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
            first_text = first.json()["response"]
            match = re.search(r"cache ref '([^']+)'", first_text)
            assert match, "Initial response should include a cache ref"
            cache_ref = match.group(1)
            self.soft_assert_equal(
                cache_ref,
                "tool/overflow_probe/pyd_ai_tool_call_id__overflow_probe",
                "Initial cache ref should use the deterministic overflow_probe tool call id",
            )

            second = self.call_api(
                "/api/chat/execute",
                method="POST",
                data={
                    "vault_name": vault.name,
                    "prompt": "Inspect the cached artifact and show the beginning.",
                    "session_id": session_id,
                    "tools": ["code_execution_local"],
                    "model": "test",
                },
            )
            assert second.status_code == 200, "First cache exploration pass should succeed"
            second_text = second.json()["response"]
            self.soft_assert(
                "OVERFLOW_SEGMENT" in second_text,
                "First cache exploration pass should read the cached artifact content",
            )

            third = self.call_api(
                "/api/chat/execute",
                method="POST",
                data={
                    "vault_name": vault.name,
                    "prompt": "Inspect the same cached artifact again and count the repeated token.",
                    "session_id": session_id,
                    "tools": ["code_execution_local"],
                    "model": "test",
                },
            )
            assert third.status_code == 200, "Second cache exploration pass should succeed"
            third_text = third.json()["response"]
            self.soft_assert(
                "1200" in third_text,
                "Second cache exploration pass should revisit the same artifact and compute a deterministic result",
            )

            runtime = get_runtime_context()
            artifact = get_cache_artifact(
                owner_id=f"{vault.name}/chat/{session_id}",
                session_key=session_id,
                artifact_ref=cache_ref,
                now=datetime.now(),
                week_start_day=0,
                system_root=runtime.config.system_root,
            )
            assert artifact is not None, "Original cached overflow artifact should still exist for later passes"

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
            api_endpoints.session_manager.get_history = original_get_history
            await self.stop_system()
            self.teardown_scenario()
