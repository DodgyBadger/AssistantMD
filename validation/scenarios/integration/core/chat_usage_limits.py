"""Validate chat model-request and tool-call usage limit handling."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from pydantic_ai.exceptions import UsageLimitExceeded

from core.chat.executor import (
    ChatModelRequestLimitError,
    PreparedChatExecution,
    _failure_recovery_message,
    execute_chat_prompt,
    execute_chat_prompt_stream,
)
from validation.core.base_scenario import BaseScenario


class _RequestLimitAgent:
    """Fake agent that raises Pydantic AI's request-limit exception."""

    async def run(self, *args, **kwargs):
        raise UsageLimitExceeded("The next request would exceed the request_limit of 150")

    async def run_stream_events(self, *args, **kwargs):
        raise UsageLimitExceeded("The next request would exceed the request_limit of 150")
        yield None


class ChatUsageLimitsScenario(BaseScenario):
    """Validate model-request limits are explicit and recoverable in chat paths."""

    async def test_scenario(self):
        vault = self.create_vault("ChatUsageLimitsVault")
        await self.start_system()

        import core.chat.executor as chat_executor

        original_prepare_chat_execution = chat_executor._prepare_chat_execution
        original_chat_usage_limits = chat_executor._chat_usage_limits

        async def _prepared_request_limit(*args, **kwargs):
            return PreparedChatExecution(
                agent=_RequestLimitAgent(),
                message_history=None,
                prompt_for_history="Trigger the request limit.",
                user_prompt="Trigger the request limit.",
                attached_image_count=0,
                model="test",
                tools=[],
            )

        chat_executor._prepare_chat_execution = _prepared_request_limit
        try:
            usage_limits = original_chat_usage_limits()
            self.soft_assert_equal(
                usage_limits.request_limit,
                150,
                "Chat usage limits should set AssistantMD's explicit model-request default",
            )
            self.soft_assert_equal(
                usage_limits.tool_calls_limit,
                None,
                "A disabled chat tool-call setting should become Pydantic None",
            )

            non_stream_session = "chat_usage_limit_non_stream"
            caught = None
            try:
                await execute_chat_prompt(
                    vault_name=vault.name,
                    vault_path=str(vault),
                    prompt="Trigger request limit.",
                    image_paths=[],
                    image_uploads=[],
                    session_id=non_stream_session,
                    tools=[],
                    model="test",
                    context_template=None,
                )
            except ChatModelRequestLimitError as exc:
                caught = exc

            self.soft_assert(caught is not None, "Non-streaming request limit should raise explicit chat error")
            if caught is not None:
                self.soft_assert(
                    "goal_ops checkpoints" in str(caught),
                    "Request-limit message should direct continuation toward durable goal state",
                )
                self.soft_assert_equal(
                    caught.details.get("setting"),
                    "chat_model_requests_limit",
                    "Request-limit error should identify the controlling setting",
                )
                self.soft_assert_equal(
                    caught.details.get("limit_kind"),
                    "request_limit",
                    "Request-limit error should identify the Pydantic limit kind",
                )

            detail = self.call_api(f"/api/chat/sessions/{non_stream_session}?vault_name={vault.name}")
            self.soft_assert_equal(detail.status_code, 200, "Failed non-streaming session detail should load")
            latest_failure = detail.json().get("latest_failure")
            self.soft_assert(latest_failure is not None, "Request-limit failure should persist recovery marker")
            if latest_failure:
                self.soft_assert_equal(
                    latest_failure.get("error_type"),
                    "UsageLimitExceeded",
                    "Failure marker should keep original Pydantic exception type",
                )
                recovery_message = _failure_recovery_message(latest_failure)
                recovery_text = ""
                if recovery_message:
                    recovery_text = " ".join(str(getattr(part, "content", "")) for part in recovery_message.parts)
                self.soft_assert(
                    "goal_ops goals/checkpoints" in recovery_text,
                    "Recovery context should direct the next turn to durable goal checkpoints",
                )
                self.soft_assert(
                    "smaller visible batch" in recovery_text,
                    "Recovery context should ask the next turn to continue in bounded visible work",
                )

            stream_session = "chat_usage_limit_stream"
            chunks = []
            async for chunk in execute_chat_prompt_stream(
                vault_name=vault.name,
                vault_path=str(vault),
                prompt="Trigger streaming request limit.",
                image_paths=[],
                image_uploads=[],
                session_id=stream_session,
                tools=[],
                model="test",
                context_template=None,
            ):
                chunks.append(chunk)

            self.soft_assert(
                any('"event": "error"' in chunk for chunk in chunks),
                "Streaming request limit should emit an SSE error event",
            )
            stream_error = self._first_sse_event(chunks, "error")
            self.soft_assert(stream_error is not None, "Streaming error event should parse")
            if stream_error:
                self.soft_assert(
                    "Model-request limit reached" in stream_error["choices"][0]["delta"]["content"],
                    "Streaming request limit should use model-request wording",
                )
                self.soft_assert(
                    "goal_ops checkpoints" in stream_error["choices"][0]["delta"]["content"],
                    "Streaming request-limit message should direct continuation toward durable goal state",
                )
                self.soft_assert_equal(
                    stream_error.get("details", {}).get("setting"),
                    "chat_model_requests_limit",
                    "Streaming request-limit details should identify the setting",
                )

            stream_detail = self.call_api(f"/api/chat/sessions/{stream_session}?vault_name={vault.name}")
            self.soft_assert_equal(stream_detail.status_code, 200, "Failed streaming session detail should load")
            self.soft_assert(
                stream_detail.json().get("latest_failure") is not None,
                "Streaming request-limit failure should persist recovery marker",
            )
        finally:
            chat_executor._prepare_chat_execution = original_prepare_chat_execution
            await self.stop_system()
            self.teardown_scenario()

        self.assert_no_failures()

    @staticmethod
    def _first_sse_event(chunks: list[str], event_name: str) -> dict | None:
        for chunk in chunks:
            if not chunk.startswith("data: "):
                continue
            payload = json.loads(chunk.removeprefix("data: ").strip())
            if payload.get("event") == event_name:
                return payload
        return None
