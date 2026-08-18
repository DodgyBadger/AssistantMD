"""Validate bounded automatic recovery for tool-free primary chat streams."""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
from pydantic_ai import Agent, AgentRunResultEvent, PartStartEvent
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from core.chat.executor import PreparedChatExecution
from core.chat.run_recovery import ChatRunRecoveryCoordinator
from validation.core.base_scenario import BaseScenario
from validation.core.streaming import stream_events_context


class _FakeStreamResult:
    def __init__(self, prompt: str, response: str) -> None:
        self._prompt = prompt
        self._response = response
        self.output = response

    def new_messages(self):
        return [
            ModelRequest(parts=[UserPromptPart(content=self._prompt)]),
            ModelResponse(parts=[TextPart(self._response)]),
        ]


class _FlakyStreamAgent:
    def __init__(self, failures: int) -> None:
        self.remaining_failures = failures
        self.attempts = 0
        self.usage_ids: list[int] = []

    @stream_events_context
    async def run_stream_events(self, prompt, **kwargs):
        self.attempts += 1
        self.usage_ids.append(id(kwargs.get("usage")))
        if self.remaining_failures:
            self.remaining_failures -= 1
            yield PartStartEvent(index=0, part=TextPart("discarded partial response"))
            request = httpx.Request("POST", "https://provider.invalid/stream")
            raise httpx.ReadError("stream disconnected", request=request)
        response = "recovered primary response"
        yield PartStartEvent(index=0, part=TextPart(response))
        yield AgentRunResultEvent(result=_FakeStreamResult(prompt, response))


class ChatStreamAutoRetryScenario(BaseScenario):
    """Prove safe primary-chat retries and the explicit disable control."""

    async def test_scenario(self):
        vault = self.create_vault("ChatStreamAutoRetryVault")
        await self.start_system()

        import core.chat.executor as chat_executor

        agents: list[_FlakyStreamAgent] = []

        async def _prepared_failure(*args, **kwargs):
            del args
            prompt = kwargs.get("prompt", "retry primary stream")
            agent = _FlakyStreamAgent(failures=1)
            agents.append(agent)
            return PreparedChatExecution(
                agent=agent,
                message_history=None,
                prompt_for_history=prompt,
                user_prompt=prompt,
                attached_image_count=0,
                model="test",
                tools=[],
            )

        original_prepare = chat_executor._prepare_chat_execution
        chat_executor._prepare_chat_execution = _prepared_failure
        try:
            delay_update = self.call_api(
                "/api/system/settings/general/model_stream_retry_base_delay_seconds",
                method="PUT",
                data={"value": "0"},
            )
            assert delay_update.status_code == 200, "Retry delay should be configurable"

            recovered = await self.run_chat_task(
                {
                    "vault_name": vault.name,
                    "prompt": "retry primary stream",
                    "session_id": "primary_auto_retry",
                    "tools": [],
                    "model": "test",
                }
            )
            retry_events = [
                event
                for event in recovered["events"]
                if event.get("event") == "chat_retry_scheduled"
            ]
            assert recovered["terminal_event"].get("event") == "done"
            assert recovered["text"] == "recovered primary response"
            assert agents[0].attempts == 2
            assert len(set(agents[0].usage_ids)) == 1, "Attempts share Pydantic usage"
            assert len(retry_events) == 1
            assert retry_events[0].get("reset_response") is True
            assert retry_events[0].get("replay_scope") == "no_chat_tools"

            checkpoint_agent, tool_effects = _checkpoint_recovery_agent(
                session_id="primary_checkpoint_retry"
            )

            async def _prepared_checkpoint(*args, **kwargs):
                del args, kwargs
                agent, recovery = checkpoint_agent
                return PreparedChatExecution(
                    agent=agent,
                    message_history=None,
                    prompt_for_history="recover after tool",
                    user_prompt="recover after tool",
                    attached_image_count=0,
                    model="test",
                    tools=["read_probe"],
                    recovery=recovery,
                )

            chat_executor._prepare_chat_execution = _prepared_checkpoint
            checkpoint_recovered = await self.run_chat_task(
                {
                    "vault_name": vault.name,
                    "prompt": "recover after tool",
                    "session_id": "primary_checkpoint_retry",
                    "tools": ["read_probe"],
                    "model": "test",
                }
            )
            checkpoint_events = [
                event
                for event in checkpoint_recovered["events"]
                if event.get("event") == "chat_retry_scheduled"
            ]
            selected_events = [
                event
                for event in checkpoint_recovered["events"]
                if event.get("event") == "chat_recovery_checkpoint_selected"
            ]
            assert checkpoint_recovered["terminal_event"].get("event") == "done"
            assert checkpoint_recovered["text"] == "recovered after checkpoint"
            assert tool_effects == [
                "first",
                "second",
            ], "Completed tools must not be replayed"
            assert len(checkpoint_events) == 1
            assert len(selected_events) == 1
            assert checkpoint_events[0].get("replay_scope") == "settled_checkpoint"
            assert checkpoint_events[0].get("trimmed_failed_response") is True

            history = chat_executor._CHAT_STORE.get_history(
                "primary_checkpoint_retry", vault.name
            )
            parts = [part for message in history for part in message.parts]
            assert sum(isinstance(part, ToolCallPart) for part in parts) == 2
            assert sum(isinstance(part, ToolReturnPart) for part in parts) == 2
            assert not any(
                isinstance(part, TextPart) and "discarded" in part.content
                for part in parts
            )

            disabled_update = self.call_api(
                "/api/system/settings/general/model_stream_retries",
                method="PUT",
                data={"value": "0"},
            )
            assert disabled_update.status_code == 200, "Automatic retry can be disabled"
            chat_executor._prepare_chat_execution = _prepared_failure
            disabled = await self.run_chat_task(
                {
                    "vault_name": vault.name,
                    "prompt": "do not retry primary stream",
                    "session_id": "primary_retry_disabled",
                    "tools": [],
                    "model": "test",
                }
            )
            assert disabled["terminal_event"].get("event") == "error"
            assert agents[1].attempts == 1
            assert not any(
                event.get("event") == "chat_retry_scheduled"
                for event in disabled["events"]
            )
        finally:
            chat_executor._prepare_chat_execution = original_prepare
            await self.stop_system()
            self.teardown_scenario()


def _checkpoint_recovery_agent(
    *, session_id: str
) -> tuple[tuple[Agent[Any, str], ChatRunRecoveryCoordinator], list[str]]:
    """Build an agent that disconnects after one completed read-only tool."""
    stream_calls = 0
    tool_effects: list[str] = []

    async def stream(
        messages: list[Any], _info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        nonlocal stream_calls
        stream_calls += 1
        tool_return_count = sum(
            isinstance(part, ToolReturnPart)
            for message in messages
            for part in message.parts
        )
        if tool_return_count < 2:
            value = "first" if tool_return_count == 0 else "second"
            yield {
                0: DeltaToolCall(
                    name="read_probe",
                    json_args=f'{{"value":"{value}"}}',
                    tool_call_id=f"read-probe-{tool_return_count + 1}",
                )
            }
            return
        if stream_calls == 3:
            yield "discarded partial response"
            request = httpx.Request("POST", "https://provider.invalid/stream")
            raise httpx.ReadError("stream disconnected", request=request)
        yield "recovered after checkpoint"

    recovery = ChatRunRecoveryCoordinator()
    agent = Agent(
        FunctionModel(stream_function=stream),
        capabilities=[recovery.capability(session_id=session_id)],
    )

    @agent.tool_plain
    async def read_probe(value: str) -> str:
        tool_effects.append(value)
        return "read complete"

    return (agent, recovery), tool_effects
