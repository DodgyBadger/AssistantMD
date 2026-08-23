"""Process-local event buffers for task-owned chat execution."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

CHAT_TASK_TERMINAL_EVENTS = frozenset(
    {"done", "cancelled", "error", "chat_retry_redirect"}
)


class ChatTaskEventCursorExpired(ValueError):
    """A replay cursor precedes the oldest retained event for a task."""

    def __init__(
        self,
        *,
        task_id: str,
        after_sequence: int,
        oldest_available_sequence: int,
        latest_sequence: int,
    ) -> None:
        super().__init__(
            f"Chat task event cursor {after_sequence} expired for task {task_id}"
        )
        self.task_id = task_id
        self.after_sequence = after_sequence
        self.oldest_available_sequence = oldest_available_sequence
        self.latest_sequence = latest_sequence


@dataclass(frozen=True)
class ChatTaskEvent:
    """One buffered event emitted by a chat execution task."""

    task_id: str
    sequence: int
    event: str
    data: dict[str, Any]
    created_at: datetime

    @property
    def is_terminal(self) -> bool:
        """Return whether this event closes the task event stream."""
        return self.event in CHAT_TASK_TERMINAL_EVENTS


@dataclass
class _ChatTaskEventStream:
    task_id: str
    events: deque[ChatTaskEvent] = field(default_factory=deque)
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    next_sequence: int = 1
    terminal_sequence: int | None = None


class ChatTaskEventBuffer:
    """In-memory chat task event buffer with replayable async subscriptions."""

    def __init__(
        self,
        *,
        max_events_per_task: int = 500,
        max_terminal_tasks: int = 100,
    ) -> None:
        if max_events_per_task < 1:
            raise ValueError("max_events_per_task must be at least 1")
        if max_terminal_tasks < 1:
            raise ValueError("max_terminal_tasks must be at least 1")
        self._max_events_per_task = max_events_per_task
        self._max_terminal_tasks = max_terminal_tasks
        self._streams: dict[str, _ChatTaskEventStream] = {}
        self._terminal_order: deque[str] = deque()
        self._lock = asyncio.Lock()

    async def append(
        self,
        task_id: str,
        event: str,
        data: dict[str, Any] | None = None,
    ) -> ChatTaskEvent:
        """Append one event and wake subscribers."""
        if not task_id:
            raise ValueError("task_id is required")
        clean_event = event.strip()
        if not clean_event:
            raise ValueError("event is required")

        async with self._lock:
            stream = self._streams.get(task_id)
            if stream is None:
                stream = _ChatTaskEventStream(task_id=task_id)
                self._streams[task_id] = stream
            if stream.terminal_sequence is not None:
                raise RuntimeError(f"Chat task event stream is terminal: {task_id}")

            buffered_event = ChatTaskEvent(
                task_id=task_id,
                sequence=stream.next_sequence,
                event=clean_event,
                data=dict(data or {}),
                created_at=datetime.now(UTC),
            )
            stream.next_sequence += 1
            stream.events.append(buffered_event)
            self._trim_stream_events(stream)
            if buffered_event.is_terminal:
                stream.terminal_sequence = buffered_event.sequence
                self._remember_terminal(task_id)
            changed = stream.changed
            stream.changed = asyncio.Event()

        changed.set()
        return buffered_event

    async def events_after(
        self,
        task_id: str,
        after_sequence: int = 0,
    ) -> list[ChatTaskEvent]:
        """Return buffered events with sequence greater than the cursor."""
        async with self._lock:
            stream = self._streams.get(task_id)
            if stream is None:
                return []
            self._raise_if_cursor_expired(stream, after_sequence=after_sequence)
            return [event for event in stream.events if event.sequence > after_sequence]

    async def ensure_cursor_available(
        self,
        task_id: str,
        *,
        after_sequence: int = 0,
    ) -> None:
        """Reject a cursor when retained replay can no longer be complete."""
        async with self._lock:
            stream = self._streams.get(task_id)
            if stream is not None:
                self._raise_if_cursor_expired(stream, after_sequence=after_sequence)

    async def is_terminal(self, task_id: str) -> bool:
        """Return whether a task stream has received a terminal event."""
        async with self._lock:
            stream = self._streams.get(task_id)
            return stream is not None and stream.terminal_sequence is not None

    async def has_stream(self, task_id: str) -> bool:
        """Return whether buffered state is retained for a task stream."""
        async with self._lock:
            return task_id in self._streams

    async def subscribe(
        self,
        task_id: str,
        *,
        after_sequence: int = 0,
    ) -> AsyncIterator[ChatTaskEvent]:
        """Yield buffered and future events until the stream reaches terminal."""
        cursor = after_sequence
        while True:
            events, terminal_seen, changed = await self._subscription_state(
                task_id,
                after_sequence=cursor,
            )
            for event in events:
                cursor = event.sequence
                yield event
                if event.is_terminal:
                    return
            if terminal_seen:
                return
            await changed.wait()

    async def _subscription_state(
        self,
        task_id: str,
        *,
        after_sequence: int,
    ) -> tuple[list[ChatTaskEvent], bool, asyncio.Event]:
        async with self._lock:
            stream = self._streams.get(task_id)
            if stream is None:
                stream = _ChatTaskEventStream(task_id=task_id)
                self._streams[task_id] = stream
            self._raise_if_cursor_expired(stream, after_sequence=after_sequence)
            events = [
                event for event in stream.events if event.sequence > after_sequence
            ]
            terminal_seen = (
                stream.terminal_sequence is not None
                and stream.terminal_sequence <= after_sequence
            )
            return events, terminal_seen, stream.changed

    @staticmethod
    def _raise_if_cursor_expired(
        stream: _ChatTaskEventStream,
        *,
        after_sequence: int,
    ) -> None:
        if not stream.events:
            return
        oldest_available_sequence = stream.events[0].sequence
        if after_sequence >= oldest_available_sequence - 1:
            return
        raise ChatTaskEventCursorExpired(
            task_id=stream.task_id,
            after_sequence=after_sequence,
            oldest_available_sequence=oldest_available_sequence,
            latest_sequence=stream.events[-1].sequence,
        )

    def _trim_stream_events(self, stream: _ChatTaskEventStream) -> None:
        while len(stream.events) > self._max_events_per_task:
            stream.events.popleft()

    def _remember_terminal(self, task_id: str) -> None:
        if task_id in self._terminal_order:
            self._terminal_order.remove(task_id)
        self._terminal_order.append(task_id)
        while len(self._terminal_order) > self._max_terminal_tasks:
            stale_task_id = self._terminal_order.popleft()
            stale_stream = self._streams.get(stale_task_id)
            if stale_stream is None or stale_stream.terminal_sequence is None:
                continue
            del self._streams[stale_task_id]
