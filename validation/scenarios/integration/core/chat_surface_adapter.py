"""Validate the surface-neutral chat adapter contract."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from pydantic_ai import AgentRunResultEvent, PartStartEvent
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from core.chat import executor as chat_executor
from core.chat.executor import PreparedChatExecution
from core.chat.surface_adapter import (
    ChatSurfaceRequest,
    cancel_chat_surface_task,
    start_chat_surface_task,
    subscribe_chat_surface_events,
)
from core.runtime.state import get_runtime_context
from validation.core.base_scenario import BaseScenario


class _FakeStreamResult:
    def __init__(self, prompt: str, response: str) -> None:
        self._prompt = prompt
        self._response = response

    def new_messages(self):
        return [
            ModelRequest(parts=[UserPromptPart(content=self._prompt)]),
            ModelResponse(parts=[TextPart(self._response)]),
        ]


class _CompletingSurfaceAgent:
    async def run_stream_events(self, *args, **kwargs):
        yield PartStartEvent(index=0, part=TextPart("surface delta"))
        yield AgentRunResultEvent(
            result=_FakeStreamResult(
                prompt="surface prompt",
                response="surface final response",
            )
        )


class _BlockingSurfaceAgent:
    async def run_stream_events(self, *args, **kwargs):
        yield PartStartEvent(index=0, part=TextPart("blocked surface delta"))
        await asyncio.Event().wait()


class ChatSurfaceAdapterScenario(BaseScenario):
    """Validate fake external chat surfaces without platform-specific code."""

    async def test_scenario(self):
        vault = self.create_vault("ChatSurfaceAdapterVault")
        await self.start_system()

        original_prepare = chat_executor._prepare_chat_execution

        async def fake_prepare_chat_execution(
            *,
            vault_name,
            vault_path,
            prompt,
            image_paths,
            image_uploads,
            session_id,
            tools,
            model,
            thinking=None,
            context_template=None,
        ):
            del vault_path, image_paths, image_uploads, thinking
            history = chat_executor._CHAT_STORE.get_history(session_id, vault_name) or []
            agent = (
                _BlockingSurfaceAgent()
                if prompt == "cancel surface prompt"
                else _CompletingSurfaceAgent()
            )
            return PreparedChatExecution(
                agent=agent,
                message_history=list(history),
                prompt_for_history=prompt,
                user_prompt=prompt,
                attached_image_count=0,
                model=model,
                tools=list(tools),
                context_template=context_template,
            )

        chat_executor._prepare_chat_execution = fake_prepare_chat_execution
        try:
            completed = await start_chat_surface_task(
                ChatSurfaceRequest(
                    surface="telegram",
                    external_conversation_id="telegram-chat-123",
                    vault_name=vault.name,
                    session_id="telegram-session",
                    prompt="surface prompt",
                    model="test",
                    tools=[],
                    metadata={"sender": "validation-user"},
                )
            )
            completed_events = await self._collect_events(completed.task.task_id)
            completed_task = await self._wait_for_task_terminal(completed.task.task_id)

            cancelled = await start_chat_surface_task(
                ChatSurfaceRequest(
                    surface="discord",
                    external_conversation_id="discord-channel-456",
                    vault_name=vault.name,
                    session_id="discord-session",
                    prompt="cancel surface prompt",
                    model="test",
                    tools=[],
                )
            )
            running_task = await self._wait_for_task_status(cancelled.task.task_id, "running")
            cancellation = await cancel_chat_surface_task(cancelled.task.task_id)
            cancelled_events = await self._collect_events(cancelled.task.task_id)
            cancelled_task = await self._wait_for_task_terminal(cancelled.task.task_id)
        finally:
            chat_executor._prepare_chat_execution = original_prepare

        self.soft_assert(
            any(event.data.get("event") == "delta" for event in completed_events)
            and any(event.data.get("event") == "done" for event in completed_events),
            "Surface adapter should expose normal chat task stream events",
        )
        self.soft_assert_equal(
            completed_task.status if completed_task else None,
            "completed",
            "Surface-started chat task should complete",
        )
        self.soft_assert_equal(
            completed_task.metadata.get("surface") if completed_task else None,
            "telegram",
            "Surface-started task should retain source surface metadata",
        )
        self.soft_assert_equal(
            completed_task.metadata.get("external_conversation_id") if completed_task else None,
            "telegram-chat-123",
            "Surface-started task should retain external conversation id",
        )
        history = chat_executor._CHAT_STORE.get_history("telegram-session", vault.name) or []
        self.soft_assert(
            len(history) >= 2,
            "Surface-started chat task should persist normal chat session history",
        )

        self.soft_assert_equal(
            running_task.status if running_task else None,
            "running",
            "Second surface task should be running before cancellation",
        )
        self.soft_assert(
            cancellation is not None and cancellation.effective,
            "Surface cancellation should map to execution task cancellation",
        )
        self.soft_assert(
            any(event.data.get("event") == "cancelled" for event in cancelled_events),
            "Surface cancellation should publish a cancelled stream event",
        )
        self.soft_assert_equal(
            cancelled_task.status if cancelled_task else None,
            "cancelled",
            "Cancelled surface task should reach cancelled terminal state",
        )

        await self.stop_system()
        self.teardown_scenario()
        self.assert_no_failures()

    async def _collect_events(self, task_id: str):
        events = []
        async for event in subscribe_chat_surface_events(task_id):
            events.append(event)
        return events

    async def _wait_for_task_status(self, task_id: str, status: str):
        runtime = get_runtime_context()
        for _ in range(100):
            task = await runtime.task_coordinator.get_task(task_id)
            if task is not None and task.status == status:
                return task
            await asyncio.sleep(0.02)
        return None

    async def _wait_for_task_terminal(self, task_id: str):
        runtime = get_runtime_context()
        for _ in range(100):
            task = await runtime.task_coordinator.get_task(task_id)
            if task is not None and task.is_terminal:
                return task
            await asyncio.sleep(0.02)
        return None
