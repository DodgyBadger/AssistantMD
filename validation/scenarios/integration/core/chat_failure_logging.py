"""
Integration scenario that forces chat execution failure and verifies the
activity log captures session-scoped diagnostics.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class ChatFailureLoggingScenario(BaseScenario):
    """Validate chat failure hardening leaves durable activity log evidence."""

    async def test_scenario(self):
        vault = self.create_vault("ChatFailureVault")

        await self.start_system()

        import core.chat.executor as chat_executor

        async def _forced_failure(*args, **kwargs):
            raise RuntimeError("forced chat failure for logging validation")

        original_prepare_chat_execution = chat_executor._prepare_chat_execution
        chat_executor._prepare_chat_execution = _forced_failure
        try:
            prompt = "Trigger the forced chat failure."
            response = self.call_api(
                "/api/chat/execute",
                method="POST",
                data={
                    "vault_name": vault.name,
                    "prompt": prompt,
                    "session_id": "chat_failure_session",
                    "tools": [],
                    "model": "test",
                },
            )
            assert response.status_code == 500, "Forced chat failure should return 500"

            transcript = vault / "AssistantMD" / "Chat_Sessions" / "chat_failure_session.md"
            assert not transcript.exists(), "Failed chat execution should not write a transcript by default"

            activity_log = self.call_api("/api/system/activity-log")
            assert activity_log.status_code == 200, "Activity log fetch should succeed"
            content = activity_log.json()["content"]

            assert '"message": "Chat request accepted"' in content, (
                "Activity log should include chat request acceptance"
            )
            assert '"message": "Chat execution failed"' in content, (
                "Activity log should include structured chat execution failure"
            )
            assert '"message": "Chat request failed before response"' in content, (
                "Activity log should include API-layer failure context"
            )
            assert '"session_id": "chat_failure_session"' in content, (
                "Activity log should include the failing session id"
            )
            assert '"error_type": "RuntimeError"' in content, (
                "Activity log should include the exception type"
            )
            assert 'forced chat failure for logging validation' in content, (
                "Activity log should include the failure message"
            )
        finally:
            chat_executor._prepare_chat_execution = original_prepare_chat_execution
            await self.stop_system()
            self.teardown_scenario()
