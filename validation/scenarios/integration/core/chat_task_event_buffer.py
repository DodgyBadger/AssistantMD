"""Validate process-local chat task event buffer behavior."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from core.chat.task_events import ChatTaskEventBuffer
from validation.core.base_scenario import BaseScenario


class ChatTaskEventBufferScenario(BaseScenario):
    """Validate replay, wakeup, terminal close, and retention semantics."""

    async def test_scenario(self):
        buffer = ChatTaskEventBuffer(max_events_per_task=3, max_terminal_tasks=1)

        first = await buffer.append(
            "task-alpha",
            "delta",
            {"text": "hello"},
        )
        second = await buffer.append(
            "task-alpha",
            "tool_call_started",
            {"tool_name": "delegate"},
        )
        replay = await buffer.events_after("task-alpha", after_sequence=0)
        self.soft_assert_equal(
            [event.sequence for event in replay],
            [first.sequence, second.sequence],
            "Buffered events should replay in sequence order",
        )
        self.soft_assert_equal(
            replay[0].data,
            {"text": "hello"},
            "Buffered event data should be preserved",
        )

        subscriber_events = []

        async def _collect_until_done() -> None:
            async for event in buffer.subscribe("task-beta"):
                subscriber_events.append(event)

        subscriber = asyncio.create_task(_collect_until_done())
        try:
            await asyncio.sleep(0)
            await buffer.append("task-beta", "delta", {"text": "wake"})
            await buffer.append("task-beta", "done", {"finish_reason": "stop"})
            await asyncio.wait_for(subscriber, timeout=1)
        finally:
            if not subscriber.done():
                subscriber.cancel()

        self.soft_assert_equal(
            [event.event for event in subscriber_events],
            ["delta", "done"],
            "Subscriber should wake for new events and stop at terminal event",
        )
        self.soft_assert(
            await buffer.is_terminal("task-beta"),
            "Terminal event should mark the task event stream terminal",
        )

        terminal_replay = []
        async for event in buffer.subscribe("task-beta", after_sequence=2):
            terminal_replay.append(event)
        self.soft_assert_equal(
            terminal_replay,
            [],
            "Subscribing after the terminal sequence should close immediately",
        )

        retained = ChatTaskEventBuffer(max_events_per_task=2, max_terminal_tasks=1)
        await retained.append("task-gamma", "delta", {"index": 1})
        await retained.append("task-gamma", "delta", {"index": 2})
        await retained.append("task-gamma", "done", {"index": 3})
        gamma_events = await retained.events_after("task-gamma")
        self.soft_assert_equal(
            [event.sequence for event in gamma_events],
            [2, 3],
            "Per-task event retention should keep the newest events",
        )

        await retained.append("task-delta", "done", {})
        self.soft_assert_equal(
            await retained.events_after("task-gamma"),
            [],
            "Terminal task retention should prune older terminal task streams",
        )
        self.soft_assert_equal(
            [event.event for event in await retained.events_after("task-delta")],
            ["done"],
            "Newest terminal task stream should remain replayable",
        )

        self.assert_no_failures()
