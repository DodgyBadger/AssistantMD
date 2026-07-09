"""Probe Pydantic AI deferred tool review behavior for inline editing."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from pydantic_ai import (
    Agent,
    AgentRunResultEvent,
    DeferredToolRequests,
    DeferredToolResults,
    ToolApproved,
    ToolDenied,
)
from pydantic_ai.messages import FunctionToolCallEvent, ToolReturnPart
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import Tool

from validation.core.base_scenario import BaseScenario


class DeferredToolReviewProbeScenario(BaseScenario):
    """Document deferred approval mechanics before production integration."""

    async def test_scenario(self) -> None:
        calls: list[tuple[str, str]] = []

        def reviewed_write(path: str, content: str) -> str:
            calls.append((path, content))
            return f"wrote {path}: {content}"

        agent = Agent(
            model=TestModel(call_tools=["reviewed_write"], custom_output_text="done"),
            tools=[
                Tool(
                    reviewed_write,
                    name="reviewed_write",
                    requires_approval=True,
                )
            ],
            output_type=[str, DeferredToolRequests],
        )

        first_result = await agent.run("write a file")
        assert isinstance(
            first_result.output, DeferredToolRequests
        ), "Deferred tool call should become run output"
        assert not calls, "Deferred tool should not execute before approval"
        assert len(first_result.output.approvals) == 1, "One approval request should be returned"

        approval_call = first_result.output.approvals[0]
        assert (
            approval_call.tool_name == "reviewed_write"
        ), "Approval request should preserve tool name"
        assert approval_call.tool_call_id, "Approval request should include a tool call id"
        assert dict(approval_call.args) == {
            "path": "a",
            "content": "a",
        }, "TestModel should provide deterministic tool args"

        approved_result = await agent.run(
            message_history=first_result.all_messages(),
            deferred_tool_results=DeferredToolResults(
                approvals={
                    approval_call.tool_call_id: ToolApproved(
                        override_args={
                            "path": "reviewed.md",
                            "content": "edited content",
                        }
                    )
                }
            ),
        )
        assert approved_result.output == "done", "Approved resume should complete normally"
        assert calls == [
            ("reviewed.md", "edited content")
        ], "ToolApproved override_args should replace original tool args"
        approved_tool_return = _first_tool_return(approved_result.new_messages())
        assert (
            approved_tool_return is not None
        ), "Approved resume should add a canonical tool return message"
        assert (
            approved_tool_return.tool_call_id == approval_call.tool_call_id
        ), "Approved tool return should use the original tool call id"

        denied_first_result = await agent.run("write another file")
        denied_call = denied_first_result.output.approvals[0]
        denied_result = await agent.run(
            message_history=denied_first_result.all_messages(),
            deferred_tool_results=DeferredToolResults(
                approvals={
                    denied_call.tool_call_id: ToolDenied(
                        "Please revise this before writing."
                    )
                }
            ),
        )
        assert denied_result.output == "done", "Denied resume should continue the agent run"
        assert calls == [
            ("reviewed.md", "edited content")
        ], "Denied deferred tool should not execute"
        denied_tool_return = _first_tool_return(denied_result.new_messages())
        assert denied_tool_return is not None, "Denied resume should add a tool return message"
        assert (
            "Please revise this before writing." in str(denied_tool_return.content)
        ), "Denied reason should be visible in canonical tool history"

        stream_events: list[Any] = []
        async for event in agent.run_stream_events("stream one deferred call"):
            stream_events.append(event)

        assert any(
            isinstance(event, FunctionToolCallEvent) for event in stream_events
        ), "Streaming deferred run should emit a tool-call event"
        final_events = [
            event for event in stream_events if isinstance(event, AgentRunResultEvent)
        ]
        assert len(final_events) == 1, "Streaming deferred run should emit one final result"
        assert isinstance(
            final_events[0].result.output, DeferredToolRequests
        ), "Streaming final output should be DeferredToolRequests"


def _first_tool_return(messages: list[Any]) -> ToolReturnPart | None:
    for message in messages:
        for part in getattr(message, "parts", ()) or ():
            if isinstance(part, ToolReturnPart):
                return part
    return None
