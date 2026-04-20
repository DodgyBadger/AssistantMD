"""
Integration scenario that forces streaming chat execution failure and verifies
the activity log captures generator-path diagnostics.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.chat import (
    PreparedChatExecution,
    execute_chat_prompt_stream,
)
from validation.core.base_scenario import BaseScenario


class _FailingStreamAgent:
    """Fake agent that fails after streaming starts."""

    async def run_stream_events(self, *args, **kwargs):
        raise RuntimeError("forced streaming chat failure for logging validation")
        yield None


class ChatStreamFailureLoggingScenario(BaseScenario):
    """Validate streaming chat failure hardening leaves activity-log evidence."""

    async def test_scenario(self):
        vault = self.create_vault("ChatStreamFailureVault")

        await self.start_system()

        import core.chat.executor as chat_executor

        async def _prepared_failure(*args, **kwargs):
            return PreparedChatExecution(
                agent=_FailingStreamAgent(),
                message_history=None,
                prompt_for_history="Trigger the forced streaming chat failure.",
                user_prompt="Trigger the forced streaming chat failure.",
                attached_image_count=0,
                model="test",
                tools=[],
            )

        original_prepare_chat_execution = chat_executor._prepare_chat_execution
        chat_executor._prepare_chat_execution = _prepared_failure
        try:
            prompt = "Trigger the forced streaming chat failure."
            stream = execute_chat_prompt_stream(
                vault_name=vault.name,
                vault_path=str(vault),
                prompt=prompt,
                image_paths=[],
                image_uploads=[],
                session_id="chat_stream_failure_session",
                tools=[],
                model="test",
                context_template=None,
            )

            chunks: list[str] = []
            caught = None
            try:
                async for chunk in stream:
                    chunks.append(chunk)
            except RuntimeError as exc:
                caught = exc

            assert caught is not None, "Streaming failure should propagate after error chunk"
            assert "forced streaming chat failure for logging validation" in str(caught), (
                "Streaming failure should preserve the original error"
            )
            assert any('"event": "error"' in chunk for chunk in chunks), (
                "Streaming failure should emit an SSE error chunk before raising"
            )

            transcript = vault / "AssistantMD" / "Chat_Sessions" / "chat_stream_failure_session.md"
            assert not transcript.exists(), "Failed streaming chat execution should not write a transcript by default"

            activity_log = self.call_api("/api/system/activity-log")
            assert activity_log.status_code == 200, "Activity log fetch should succeed"
            content = activity_log.json()["content"]

            assert '"message": "Streaming chat execution started"' in content, (
                "Activity log should include streaming start"
            )
            assert '"message": "Streaming chat execution failed"' in content, (
                "Activity log should include structured streaming failure"
            )
            assert '"session_id": "chat_stream_failure_session"' in content, (
                "Activity log should include the failing streaming session id"
            )
            assert '"error_type": "RuntimeError"' in content, (
                "Activity log should include the streaming exception type"
            )
            assert 'forced streaming chat failure for logging validation' in content, (
                "Activity log should include the streaming failure message"
            )
        finally:
            chat_executor._prepare_chat_execution = original_prepare_chat_execution
            await self.stop_system()
            self.teardown_scenario()
