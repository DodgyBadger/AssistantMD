"""
Integration scenario for cancelling an active non-streaming chat task.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.chat.executor import PreparedChatExecution, execute_chat_prompt
from core.runtime.state import get_runtime_context
from validation.core.base_scenario import BaseScenario


class _HangingAgent:
    """Fake agent that stays active until its asyncio task is cancelled."""

    async def run(self, *args, **kwargs):
        await asyncio.Event().wait()


class ChatCancellationScenario(BaseScenario):
    """Validate active chat task lookup and cancellation by session id."""

    async def test_scenario(self):
        vault = self.create_vault("ChatCancellationVault")

        await self.start_system()

        import core.chat.executor as chat_executor

        async def _prepared_hanging_chat(*args, **kwargs):
            return PreparedChatExecution(
                agent=_HangingAgent(),
                message_history=None,
                prompt_for_history="Cancel this chat.",
                user_prompt="Cancel this chat.",
                attached_image_count=0,
                model="test",
                tools=[],
            )

        original_prepare_chat_execution = chat_executor._prepare_chat_execution
        chat_executor._prepare_chat_execution = _prepared_hanging_chat
        session_id = "chat_cancellation_session"
        chat_task = None
        try:
            chat_task = asyncio.create_task(
                execute_chat_prompt(
                    vault_name=vault.name,
                    vault_path=str(vault),
                    prompt="Cancel this chat.",
                    image_paths=[],
                    image_uploads=[],
                    session_id=session_id,
                    tools=[],
                    model="test",
                    context_template=None,
                )
            )

            runtime = get_runtime_context()
            active = []
            for _ in range(50):
                active = await runtime.task_coordinator.list_tasks(
                    scope=f"chat_session:{session_id}",
                    include_terminal=False,
                )
                if active:
                    break
                await asyncio.sleep(0.05)

            assert active, "Chat execution should register an active task"
            task_id = active[-1].task_id

            active_response = self.call_api(f"/api/chat/sessions/{session_id}/active-task")
            assert active_response.status_code == 200, "Active chat task endpoint succeeds"
            assert active_response.json().get("task_id") == task_id, (
                "Active chat task endpoint returns the running task"
            )

            cancel_response = self.call_api(
                f"/api/chat/sessions/{session_id}/cancel",
                method="POST",
            )
            assert cancel_response.status_code == 200, "Chat session cancel endpoint succeeds"
            assert cancel_response.json().get("cancelled") is True, (
                "Chat session cancel should acknowledge cancellation"
            )

            caught = None
            try:
                await chat_task
            except asyncio.CancelledError as exc:
                caught = exc
            assert caught is not None, "Cancelled chat task should raise CancelledError"

            task_detail = self.call_api(f"/api/tasks/{task_id}")
            assert task_detail.status_code == 200, "Cancelled task detail remains queryable"
            assert task_detail.json().get("status") == "cancelled", (
                "Cancelled chat task should have cancelled terminal status"
            )

            active_after_cancel = self.call_api(f"/api/chat/sessions/{session_id}/active-task")
            assert active_after_cancel.status_code == 404, (
                "Cancelled chat session should no longer have an active task"
            )

            detail = self.call_api(
                f"/api/chat/sessions/{session_id}?vault_name={vault.name}"
            )
            assert detail.status_code == 200, "Cancelled chat session detail is persisted"
            messages = detail.json().get("messages", [])
            assert len(messages) == 1, "Cancelled chat should persist only the user turn"
            assert messages[0].get("role") == "user", (
                "Cancelled chat persisted message should be the user prompt"
            )
            assert "Cancel this chat." in messages[0].get("content", ""), (
                "Cancelled chat should retain the submitted prompt"
            )
        finally:
            if chat_task is not None and not chat_task.done():
                chat_task.cancel()
                try:
                    await chat_task
                except asyncio.CancelledError:
                    pass
            chat_executor._prepare_chat_execution = original_prepare_chat_execution
            await self.stop_system()
            self.teardown_scenario()
