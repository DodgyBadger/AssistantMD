"""Surface-neutral adapter helpers for external chat entry points."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from core.chat.chat_store import ChatStore
from core.chat.task_events import ChatTaskEvent
from core.chat.task_execution import (
    CHAT_TASK_EVENT_BUFFER,
    ChatStreamTaskStart,
    start_queued_chat_stream_task,
)
from core.chat.workspace import normalize_workspace_path
from core.llm.thinking import ThinkingValue, normalize_thinking_value
from core.runtime.execution_tasks import ExecutionTaskCancellationResult
from core.runtime.state import get_runtime_context


_CHAT_STORE = ChatStore()


@dataclass(frozen=True)
class ChatSurfaceRequest:
    """Normalized chat request from a non-web surface."""

    surface: str
    external_conversation_id: str
    vault_name: str
    session_id: str
    prompt: str
    model: str
    tools: list[str] = field(default_factory=list)
    thinking: ThinkingValue | str | None = None
    context_template: str | None = None
    workspace_path: str | None = None
    image_paths: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


async def start_chat_surface_task(request: ChatSurfaceRequest) -> ChatStreamTaskStart:
    """Start a queued chat task from a normalized external surface request."""
    _validate_surface_request(request)
    runtime = get_runtime_context()
    vault_path = str(runtime.config.data_root / request.vault_name)
    thinking = normalize_thinking_value(
        request.thinking,
        source_name=f"{request.surface} thinking",
    )
    workspace_path = normalize_workspace_path(request.workspace_path)
    if request.workspace_path is not None:
        _CHAT_STORE.set_session_workspace(
            session_id=request.session_id,
            vault_name=request.vault_name,
            workspace_path=workspace_path or None,
        )
    started = await start_queued_chat_stream_task(
        vault_name=request.vault_name,
        vault_path=vault_path,
        prompt=request.prompt,
        image_paths=request.image_paths,
        image_uploads=[],
        session_id=request.session_id,
        tools=request.tools,
        model=request.model,
        thinking=thinking,
        context_template=request.context_template,
    )
    await runtime.task_coordinator.update_metadata(
        started.task.task_id,
        {
            "surface": request.surface,
            "external_conversation_id": request.external_conversation_id,
            "surface_metadata": dict(request.metadata),
            "workspace_path": workspace_path or None,
        },
    )
    return ChatStreamTaskStart(
        task=await runtime.task_coordinator.get_task(started.task.task_id) or started.task,
        session_id=started.session_id,
    )


async def subscribe_chat_surface_events(
    task_id: str,
    *,
    after_sequence: int = 0,
) -> AsyncIterator[ChatTaskEvent]:
    """Subscribe to buffered task events for a surface-owned chat task."""
    async for event in CHAT_TASK_EVENT_BUFFER.subscribe(
        task_id,
        after_sequence=after_sequence,
    ):
        yield event


async def cancel_chat_surface_task(
    task_id: str,
    *,
    reason: str = "surface_cancel_requested",
) -> ExecutionTaskCancellationResult | None:
    """Cancel a surface-owned chat task by task id."""
    runtime = get_runtime_context()
    return await runtime.task_coordinator.cancel_task(task_id, reason=reason)


def _validate_surface_request(request: ChatSurfaceRequest) -> None:
    required = {
        "surface": request.surface,
        "external_conversation_id": request.external_conversation_id,
        "vault_name": request.vault_name,
        "session_id": request.session_id,
        "prompt": request.prompt,
        "model": request.model,
    }
    missing = [name for name, value in required.items() if not value.strip()]
    if missing:
        raise ValueError(f"Missing required chat surface field(s): {', '.join(missing)}")
