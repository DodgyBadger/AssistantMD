"""Validate chat task skeleton support for deferred inline reviews."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from pydantic_ai import AgentRunResultEvent, DeferredToolRequests, PartStartEvent
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from core.chat import executor as chat_executor
from core.chat.deferred_reviews import get_deferred_review
from core.chat.executor import PreparedChatExecution
from core.chat.task_execution import CHAT_TASK_EVENT_BUFFER, start_queued_chat_stream_task
from core.runtime.state import get_runtime_context
from validation.core.base_scenario import BaseScenario


class _DeferredReviewResult:
    def __init__(self, prompt: str) -> None:
        self._tool_call = ToolCallPart(
            tool_name="reviewed_write",
            args={"path": "Draft.md", "content": "Draft content"},
            tool_call_id="review-call-1",
        )
        self.output = DeferredToolRequests(approvals=[self._tool_call])
        self._messages = [
            ModelRequest(parts=[UserPromptPart(content=prompt)]),
            ModelResponse(parts=[self._tool_call]),
        ]

    def new_messages(self):
        return list(self._messages)

    def all_messages(self):
        return list(self._messages)


class _DeferredReviewAgent:
    async def run_stream_events(self, prompt, **kwargs):
        del kwargs
        yield AgentRunResultEvent(result=_DeferredReviewResult(str(prompt)))


class _ResumeResult:
    output = "resumed"

    def new_messages(self):
        return [
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="reviewed_write",
                        content="wrote reviewed draft",
                        tool_call_id="review-call-1",
                    )
                ]
            ),
            ModelResponse(parts=[TextPart("resumed")]),
        ]

    def all_messages(self):
        return self.new_messages()


class _ResumeAgent:
    def __init__(self, capture: dict) -> None:
        self.capture = capture

    async def run_stream_events(self, prompt, **kwargs):
        self.capture["prompt"] = prompt
        self.capture["deferred_tool_results"] = kwargs.get("deferred_tool_results")
        self.capture["message_history"] = kwargs.get("message_history")
        yield PartStartEvent(index=0, part=TextPart("resumed"))
        yield AgentRunResultEvent(result=_ResumeResult())


class DeferredReviewTaskSkeletonScenario(BaseScenario):
    """Validate pending review persistence from the production chat task path."""

    async def test_scenario(self) -> None:
        vault = self.create_vault("DeferredReviewTaskVault")
        await self.start_system()

        original_prepare = chat_executor._prepare_chat_execution
        original_prepare_resume = chat_executor._prepare_deferred_review_resume_execution
        resume_capture: dict = {}

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
            chat_mode="normal",
            message_history_override=None,
            display_prompt=None,
        ):
            del vault_path, image_paths, image_uploads, thinking, message_history_override
            del display_prompt
            history = chat_executor._CHAT_STORE.get_history(session_id, vault_name) or []
            return PreparedChatExecution(
                agent=_DeferredReviewAgent(),
                message_history=list(history),
                prompt_for_history=prompt,
                user_prompt=prompt,
                attached_image_count=0,
                model=model,
                tools=list(tools),
                thinking="low",
                context_template=context_template,
                chat_mode=chat_mode,
            )

        async def fake_prepare_deferred_review_resume_execution(
            *,
            vault_name,
            vault_path,
            session_id,
            tools,
            model,
            message_history,
            deferred_tool_results,
            thinking=None,
            context_template=None,
            chat_mode="normal",
        ):
            del vault_name, vault_path, session_id
            resume_capture["prepared_tools"] = list(tools)
            resume_capture["prepared_model"] = model
            resume_capture["prepared_thinking"] = thinking
            resume_capture["prepared_context_template"] = context_template
            resume_capture["prepared_chat_mode"] = chat_mode
            return PreparedChatExecution(
                agent=_ResumeAgent(resume_capture),
                message_history=list(message_history),
                prompt_for_history="",
                user_prompt=None,
                attached_image_count=0,
                model=model,
                tools=list(tools),
                context_template=context_template,
                chat_mode=chat_mode,
                deferred_tool_results=deferred_tool_results,
            )

        chat_executor._prepare_chat_execution = fake_prepare_chat_execution
        chat_executor._prepare_deferred_review_resume_execution = (
            fake_prepare_deferred_review_resume_execution
        )
        try:
            started = await start_queued_chat_stream_task(
                vault_name=vault.name,
                vault_path=str(vault),
                prompt="write draft",
                image_paths=[],
                image_uploads=[],
                session_id="deferred-review-session",
                tools=[],
                model="test",
                chat_mode="collaborative",
            )
            task = await self._wait_for_task_terminal(started.task.task_id)
            assert task is not None, "Deferred review task should complete current stream"
            assert task.status == "completed", "Deferred review task should be terminal"

            events = await CHAT_TASK_EVENT_BUFFER.events_after(started.task.task_id)
            event_names = [event.event for event in events]
            assert event_names == [
                "review_required",
                "done",
            ], "Deferred review task should emit review_required before done"
            review_event = events[0].data
            assert (
                review_event["artifact_kind"] == "deferred_tool_review"
            ), "Review event should identify deferred review artifacts"
            assert review_event["review_count"] == 1, "Review event should summarize calls"
            assert (
                events[-1].data["choices"][0]["finish_reason"] == "tool_review_required"
            ), "Done event should identify review-required finish reason"

            review = get_deferred_review(
                vault_name=vault.name,
                session_id="deferred-review-session",
                artifact_ref=review_event["artifact_ref"],
            )
            assert review is not None, "Deferred review record should be persisted"
            assert review.status == "pending", "Deferred review should start pending"
            assert review.originating_task_id == started.task.task_id
            assert review.review_count == 1
            assert len(review.resume_messages) == 2, "Resume history should be persisted"
            assert review.resume_config.get("model") == "test"
            assert review.resume_config.get("tools") == []
            assert review.resume_config.get("thinking") == "low"
            assert review.resume_config.get("chat_mode") == "collaborative"

            api_response = self.call_api(
                (
                    f"/api/vaults/{vault.name}/chat/deferred-review-session/"
                    f"deferred-reviews/{review_event['artifact_ref']}"
                )
            )
            assert api_response.status_code == 200, "Deferred review API should return artifact"
            api_payload = api_response.json()
            assert api_payload.get("artifact_kind") == "deferred_tool_review"
            assert api_payload.get("status") == "pending"
            assert api_payload.get("originating_task_id") == started.task.task_id
            assert api_payload.get("approvals", [{}])[0].get("tool_call_id") == "review-call-1"

            submit_response = self.call_api(
                (
                    f"/api/vaults/{vault.name}/chat/deferred-review-session/"
                    f"deferred-reviews/{review_event['artifact_ref']}/submit"
                ),
                method="POST",
                data={
                    "decisions": [
                        {
                            "tool_call_id": "review-call-1",
                            "decision": "approve",
                            "override_args": {
                                "path": "Reviewed.md",
                                "content": "Reviewed content",
                            },
                        }
                    ],
                },
            )
            assert submit_response.status_code == 200, "Submit should start a resume task"
            submit_payload = submit_response.json()
            assert submit_payload.get("status") == "submitted"
            resumed_task_id = submit_payload.get("task", {}).get("task_id")
            assert resumed_task_id, "Submit response should include resumed task id"
            resumed_task = await self._wait_for_task_terminal(resumed_task_id)
            assert resumed_task is not None, "Resumed task should complete"
            assert resumed_task.status == "completed"
            resumed_events = await CHAT_TASK_EVENT_BUFFER.events_after(resumed_task_id)
            assert [event.event for event in resumed_events] == [
                "delta",
                "done",
            ], "Resumed task should stream normal completion events"
            assert resume_capture["prompt"] is None, "Resume should not send a new prompt"
            result = resume_capture["deferred_tool_results"]
            assert result is not None, "Resume should receive DeferredToolResults"
            assert resume_capture["prepared_model"] == "test"
            assert resume_capture["prepared_tools"] == []
            assert resume_capture["prepared_thinking"] == "low"
            assert resume_capture["prepared_chat_mode"] == "collaborative"
            approved = result.approvals["review-call-1"]
            assert approved.override_args == {
                "path": "Reviewed.md",
                "content": "Reviewed content",
            }, "Submit should preserve edited override args"
            submitted_review = get_deferred_review(
                vault_name=vault.name,
                session_id="deferred-review-session",
                artifact_ref=review_event["artifact_ref"],
            )
            assert submitted_review is not None
            assert submitted_review.status == "submitted"
            assert submitted_review.resumed_task_id == resumed_task_id

            stale_response = self.call_api(
                (
                    f"/api/vaults/{vault.name}/chat/deferred-review-session/"
                    f"deferred-reviews/{review_event['artifact_ref']}/submit"
                ),
                method="POST",
                data={
                    "decisions": [
                        {
                            "tool_call_id": "review-call-1",
                            "decision": "approve",
                        }
                    ],
                },
            )
            assert stale_response.status_code == 409, "Repeated submit should be rejected"
        finally:
            chat_executor._prepare_chat_execution = original_prepare
            chat_executor._prepare_deferred_review_resume_execution = original_prepare_resume
            await self.stop_system()

    async def _wait_for_task_terminal(self, task_id: str):
        runtime = get_runtime_context()
        for _ in range(100):
            task = await runtime.task_coordinator.get_task(task_id)
            if task is not None and task.is_terminal:
                return task
            await asyncio.sleep(0.02)
        return None
