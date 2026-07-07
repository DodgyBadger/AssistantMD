"""Integration scenario for manually retrying interrupted chat turns."""

import asyncio
import sys
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from core.chat.executor import PreparedChatExecution
from core.utils.messages import extract_role_and_text
from validation.core.base_scenario import BaseScenario


class _InterruptedStreamAgent:
    """Fake agent that fails like an interrupted provider stream."""

    async def run_stream_events(self, *args, **kwargs):
        raise httpx.RemoteProtocolError(
            "peer closed connection without sending complete message body (incomplete chunked read)"
        )
        yield None


class ChatManualRetryScenario(BaseScenario):
    """Validate manual retry resumes the failed turn without duplicating user history."""

    async def test_scenario(self):
        vault = self.create_vault("ChatManualRetryVault")

        await self.start_system()

        import core.chat.executor as chat_executor
        from core.chat.task_execution import CHAT_TASK_EVENT_BUFFER
        from pydantic_ai.models.test import TestModel

        async def _prepared_failure(*args, **kwargs):
            return PreparedChatExecution(
                agent=_InterruptedStreamAgent(),
                message_history=None,
                prompt_for_history="Retry this interrupted request.",
                user_prompt="Retry this interrupted request.",
                attached_image_count=0,
                model="test",
                tools=[],
            )

        original_prepare_chat_execution = chat_executor._prepare_chat_execution
        original_prepare_agent_config = chat_executor._prepare_agent_config
        chat_executor._prepare_chat_execution = _prepared_failure
        session_id = "chat_manual_retry_session"
        try:
            failed_result = await self.run_chat_task(
                {
                    "vault_name": vault.name,
                    "prompt": "Retry this interrupted request.",
                    "session_id": session_id,
                    "tools": [],
                    "model": "test",
                }
            )
            assert failed_result["terminal_event"].get("event") == "error", (
                "Interrupted chat should emit an error event"
            )

            failed_detail = self.call_api(
                f"/api/chat/sessions/{session_id}?vault_name={vault.name}"
            )
            assert failed_detail.status_code == 200, "Failed chat session detail should load"
            latest_failure = failed_detail.json().get("latest_failure")
            assert latest_failure is not None, "Interrupted chat should expose a failure marker"
            assert latest_failure.get("failure_kind") == "transient_network", (
                "Interrupted provider streams should be retryable network failures"
            )
            assert latest_failure.get("retryable") is True, (
                "Interrupted provider streams should be manually retryable"
            )

            captured_retry_history: list[tuple[str, str]] = []

            def _patched_prepare_agent_config(vault_name, vault_path, tools, model, thinking=None):
                del vault_name, vault_path, tools, model, thinking
                return ("Answer briefly.", "", TestModel(), [])

            async def _capturing_prepare_chat_execution(*args, **kwargs):
                prepared = await original_prepare_chat_execution(*args, **kwargs)
                captured_retry_history.extend(
                    extract_role_and_text(message)
                    for message in (prepared.message_history or [])
                )
                return prepared

            chat_executor._prepare_agent_config = _patched_prepare_agent_config
            chat_executor._prepare_chat_execution = _capturing_prepare_chat_execution

            retry_start = self.call_api(
                f"/api/chat/sessions/{session_id}/retry",
                method="POST",
                data={"vault_name": vault.name},
            )
            assert retry_start.status_code == 200, "Manual retry should start a chat task"
            retry_payload = retry_start.json()
            task_id = retry_payload.get("task", {}).get("task_id")
            assert task_id, "Manual retry response should include a task id"

            retry_events: list[dict[str, Any]] = []
            retry_text = ""

            async def _collect_retry_events() -> None:
                nonlocal retry_text
                cursor = 0
                while True:
                    events = await CHAT_TASK_EVENT_BUFFER.events_after(task_id, cursor)
                    for buffered_event in events:
                        cursor = buffered_event.sequence
                        event = dict(buffered_event.data)
                        event.setdefault("event", buffered_event.event)
                        retry_events.append(event)
                        choices = event.get("choices") or []
                        if choices:
                            delta = choices[0].get("delta") or {}
                            content = delta.get("content")
                            if isinstance(content, str):
                                retry_text += content
                        if buffered_event.is_terminal:
                            return
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(_collect_retry_events(), timeout=10)
            assert retry_events[-1].get("event") == "done", "Manual retry should complete"
            assert retry_text, "Manual retry should stream assistant text"
            assert all(
                item != ("user", "Retry this interrupted request.")
                for item in captured_retry_history
            ), "Manual retry should not put the failed user prompt in history and prompt again"
            assert any(
                role == "system" and "previous user request was accepted" in content
                for role, content in captured_retry_history
            ), "Manual retry should keep internal recovery context"

            retried_detail = self.call_api(
                f"/api/chat/sessions/{session_id}?vault_name={vault.name}"
            )
            assert retried_detail.status_code == 200, "Retried chat session detail should load"
            payload = retried_detail.json()
            assert payload.get("latest_failure") is None, (
                "Successful manual retry should clear the failure marker"
            )
            messages = payload.get("messages", [])
            user_messages = [message for message in messages if message.get("role") == "user"]
            assistant_messages = [message for message in messages if message.get("role") == "assistant"]
            assert len(user_messages) == 1, "Manual retry should not duplicate the user message"
            assert len(assistant_messages) == 1, "Manual retry should persist one assistant response"

            activity_log = self.call_api("/api/system/activity-log")
            assert activity_log.status_code == 200, "Activity log fetch should succeed"
            content = activity_log.json()["content"]
            assert '"event": "chat_manual_retry_started"' in content, (
                "Activity log should include manual retry start evidence"
            )
        finally:
            chat_executor._prepare_chat_execution = original_prepare_chat_execution
            chat_executor._prepare_agent_config = original_prepare_agent_config
            await self.stop_system()
            self.teardown_scenario()
