"""
Integration scenario that validates oversized chat tool output is stored in
cache and replaced with a compact cache-ref notice.
"""

import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation.core.base_scenario import BaseScenario


class ChatToolOverflowCacheScenario(BaseScenario):
    """Validate chat overflow handling uses cache instead of hidden buffering."""

    async def test_scenario(self):
        vault = self.create_vault("ChatToolOverflowCacheVault")

        await self.start_system()

        import core.chat.executor as chat_executor
        from core.context.store import get_cache_artifact
        from core.runtime.state import get_runtime_context
        from pydantic_ai.models.test import TestModel

        async def overflow_probe() -> str:
            return "OVERFLOW_SEGMENT " * 1200

        def _patched_prepare_agent_config(vault_name, vault_path, tools, model):
            del vault_name, vault_path, tools, model
            return (
                "You must call the overflow_probe tool before responding.",
                "",
                TestModel(),
                [overflow_probe],
            )

        original_prepare_agent_config = chat_executor._prepare_agent_config
        chat_executor._prepare_agent_config = _patched_prepare_agent_config
        try:
            update_setting = self.call_api(
                "/api/system/settings/general/auto_buffer_max_tokens",
                method="PUT",
                data={"value": "50"},
            )
            assert update_setting.status_code == 200, "Scenario should lower chat overflow threshold"

            response = self.call_api(
                "/api/chat/execute",
                method="POST",
                data={
                    "vault_name": vault.name,
                    "prompt": "Use the overflow_probe tool and then answer briefly.",
                    "session_id": "chat_tool_overflow_cache_session",
                    "tools": ["overflow_probe"],
                    "model": "test",
                },
            )
            assert response.status_code == 200, "Chat execution with oversized tool result should succeed"

            payload = response.json()
            response_text = payload["response"]
            session_id = payload["session_id"]

            self.soft_assert("stored in cache ref '" in response_text, "Response should mention cache ref storage")
            self.soft_assert("Preview:" in response_text, "Response should include a compact preview")
            self.soft_assert("buffer" not in response_text.lower(), "Response should not refer to buffer routing")

            match = re.search(r"cache ref '([^']+)'", response_text)
            assert match, "Response should contain an extractable cache ref"
            cache_ref = match.group(1)
            self.soft_assert(
                cache_ref.startswith("tool/overflow_probe/"),
                "Cache ref should use the tool-scoped chat overflow namespace",
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
            assert artifact is not None, "Oversized chat tool output should be persisted in cache"

            self.soft_assert_equal(artifact["origin"], "chat_tool_overflow", "Cache artifact origin should be tracked")
            self.soft_assert_equal(
                artifact["metadata"].get("tool_name"),
                "overflow_probe",
                "Cache artifact metadata should record the originating tool",
            )
            self.soft_assert(
                "OVERFLOW_SEGMENT" in artifact["raw_content"],
                "Cached artifact should preserve the oversized tool payload",
            )
            self.soft_assert(
                len(artifact["raw_content"]) > len(response_text),
                "Cached artifact should retain more content than the compact chat response",
            )
        finally:
            chat_executor._prepare_agent_config = original_prepare_agent_config
            await self.stop_system()
            self.teardown_scenario()
