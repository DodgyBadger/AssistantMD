"""Validate streaming chat emits keepalives while waiting for agent events."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from core.chat.executor import PreparedChatExecution, execute_chat_prompt_stream
from validation.core.base_scenario import BaseScenario


class _DelayedStreamAgent:
    """Fake agent that stays idle long enough to require a keepalive."""

    async def run_stream_events(self, *args, **kwargs):
        await asyncio.sleep(0.05)
        if False:
            yield None


class _HangingStreamAgent:
    """Fake streaming agent that stays active until cancelled."""

    async def run_stream_events(self, *args, **kwargs):
        await asyncio.Event().wait()
        if False:
            yield None


class ChatStreamKeepaliveScenario(BaseScenario):
    """Validate SSE keepalives are emitted during idle streaming waits."""

    async def test_scenario(self):
        vault = self.create_vault("ChatStreamKeepaliveVault")
        await self.start_system()

        import core.chat.executor as chat_executor

        original_prepare_chat_execution = chat_executor._prepare_chat_execution
        original_keepalive_interval = chat_executor._STREAM_KEEPALIVE_INTERVAL_SECONDS

        async def _prepared_idle_stream(*args, **kwargs):
            return PreparedChatExecution(
                agent=_DelayedStreamAgent(),
                message_history=None,
                prompt_for_history="Trigger idle streaming.",
                user_prompt="Trigger idle streaming.",
                attached_image_count=0,
                model="test",
                tools=[],
            )

        chat_executor._prepare_chat_execution = _prepared_idle_stream
        chat_executor._STREAM_KEEPALIVE_INTERVAL_SECONDS = 0.01
        try:
            chunks: list[str] = []
            async for chunk in execute_chat_prompt_stream(
                vault_name=vault.name,
                vault_path=str(vault),
                prompt="Trigger idle streaming.",
                image_paths=[],
                image_uploads=[],
                session_id="chat_stream_keepalive_session",
                tools=[],
                model="test",
                context_template=None,
            ):
                chunks.append(chunk)

            keepalive_index = next(
                (index for index, chunk in enumerate(chunks) if chunk.startswith(": keepalive")),
                None,
            )
            done_index = next(
                (index for index, chunk in enumerate(chunks) if '"event": "done"' in chunk),
                None,
            )
            self.soft_assert(keepalive_index is not None, "Idle stream should emit a keepalive chunk")
            self.soft_assert(done_index is not None, "Idle stream should still emit the done event")
            if keepalive_index is not None and done_index is not None:
                self.soft_assert(
                    keepalive_index < done_index,
                    "Keepalive should arrive before the terminal done event",
                )

            async def _prepared_hanging_stream(*args, **kwargs):
                return PreparedChatExecution(
                    agent=_HangingStreamAgent(),
                    message_history=None,
                    prompt_for_history="Cancel idle streaming.",
                    user_prompt="Cancel idle streaming.",
                    attached_image_count=0,
                    model="test",
                    tools=[],
                )

            chat_executor._prepare_chat_execution = _prepared_hanging_stream
            cancel_session_id = "chat_stream_keepalive_cancel_session"
            cancel_chunks: list[str] = []

            async def _consume_stream() -> None:
                async for chunk in execute_chat_prompt_stream(
                    vault_name=vault.name,
                    vault_path=str(vault),
                    prompt="Cancel idle streaming.",
                    image_paths=[],
                    image_uploads=[],
                    session_id=cancel_session_id,
                    tools=[],
                    model="test",
                    context_template=None,
                ):
                    cancel_chunks.append(chunk)

            consume_task = asyncio.create_task(_consume_stream())
            try:
                active_response = None
                for _ in range(50):
                    active_response = self.call_api(
                        f"/api/chat/sessions/{cancel_session_id}/active-task"
                    )
                    if active_response.status_code == 200:
                        break
                    await asyncio.sleep(0.02)

                self.soft_assert(
                    active_response is not None and active_response.status_code == 200,
                    "Streaming run should expose an active chat task",
                )
                cancel_response = self.call_api(
                    f"/api/chat/sessions/{cancel_session_id}/cancel",
                    method="POST",
                )
                self.soft_assert_equal(
                    cancel_response.status_code,
                    200,
                    "Streaming chat session cancel endpoint should succeed",
                )
                self.soft_assert(
                    cancel_response.json().get("cancelled") is True,
                    "Streaming chat session cancel should be effective",
                )
                await asyncio.wait_for(consume_task, timeout=1)
                self.soft_assert(
                    any('"event": "cancelled"' in chunk for chunk in cancel_chunks),
                    "Streaming cancellation should emit the cancelled SSE event",
                )
            finally:
                if not consume_task.done():
                    consume_task.cancel()
        finally:
            chat_executor._prepare_chat_execution = original_prepare_chat_execution
            chat_executor._STREAM_KEEPALIVE_INTERVAL_SECONDS = original_keepalive_interval
            await self.stop_system()
            self.teardown_scenario()

        self.assert_no_failures()
