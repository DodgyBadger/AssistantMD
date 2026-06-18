"""Task-owned chat streaming execution helpers."""

from __future__ import annotations

import asyncio
import contextvars
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from pydantic_ai import (
    AgentRunResultEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPartDelta,
)
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import TextPart

from core.chat import executor as chat_executor
from core.chat.chat_store import ChatStore
from core.chat.compaction import chat_session_history_lock
from core.chat.task_events import ChatTaskEventBuffer
from core.llm.capabilities.chat_context import build_context_template_error_details
from core.llm.capabilities.chat_tool_output_cache import tool_result_as_text
from core.runtime.execution_tasks import (
    ExecutionTaskKind,
    ExecutionTaskSnapshot,
    ExecutionTaskSource,
    chat_session_scope,
    chat_task_label,
)
from core.runtime.state import get_runtime_context
from core.tools.failures import classify_exception
from core.tools.utils import estimate_token_count


_CHAT_STORE = ChatStore()


@dataclass(frozen=True)
class ChatStreamTaskStart:
    """Result returned after starting a background streaming chat task."""

    task: ExecutionTaskSnapshot
    session_id: str


CHAT_TASK_EVENT_BUFFER = ChatTaskEventBuffer()
_CHAT_TASK_FAILURES: dict[str, BaseException] = {}


async def start_prepared_chat_stream_task(
    *,
    prepared: chat_executor.PreparedChatExecution,
    vault_name: str,
    vault_path: str,
    session_id: str,
    event_buffer: ChatTaskEventBuffer | None = None,
) -> ChatStreamTaskStart:
    """Start a prepared streaming chat run in a background execution task."""
    runtime = get_runtime_context()
    buffer = event_buffer or CHAT_TASK_EVENT_BUFFER
    task = await runtime.task_coordinator.create_queued_task(
        kind=ExecutionTaskKind.CHAT,
        scope=chat_session_scope(session_id),
        source=ExecutionTaskSource.API,
        label=chat_task_label(session_id),
        metadata={
            "vault": vault_name,
            "session_id": session_id,
            "streaming": True,
            "model": prepared.model,
            "tools": list(prepared.tools),
        },
    )

    async def _run() -> None:
        try:
            async with runtime.task_coordinator.track_existing_task(task.task_id) as tracked_task:
                await runtime.task_coordinator.mark_started(tracked_task.task_id)
                await _run_prepared_chat_stream_task(
                    task=tracked_task,
                    prepared=prepared,
                    vault_name=vault_name,
                    vault_path=vault_path,
                    session_id=session_id,
                    event_buffer=buffer,
                )
        except asyncio.CancelledError:
            await _append_cancelled_if_open(buffer, task.task_id)
            raise
        except Exception:  # noqa: BLE001 - task status and stream event were recorded
            if await _task_has_cancelled(task.task_id):
                await _append_cancelled_if_open(buffer, task.task_id)
            return

    background_task = asyncio.create_task(_run(), context=contextvars.Context())
    runtime.background_tasks.add(background_task)
    background_task.add_done_callback(runtime.background_tasks.discard)
    return ChatStreamTaskStart(task=task, session_id=session_id)


async def start_chat_stream_task(
    *,
    vault_name: str,
    vault_path: str,
    prompt: str,
    image_paths: list[str] | None,
    image_uploads: list[chat_executor.UploadedImageAttachment] | None,
    session_id: str,
    tools: list[str],
    model: str,
    thinking: chat_executor.ThinkingValue | None = None,
    context_template: str | None = None,
    event_buffer: ChatTaskEventBuffer | None = None,
) -> ChatStreamTaskStart:
    """Preflight and start a streaming chat run in a background execution task."""
    prepared = await chat_executor._prepare_chat_execution(
        vault_name=vault_name,
        vault_path=vault_path,
        prompt=prompt,
        image_paths=image_paths,
        image_uploads=image_uploads,
        session_id=session_id,
        tools=tools,
        model=model,
        thinking=thinking,
        context_template=context_template,
    )
    return await start_prepared_chat_stream_task(
        prepared=prepared,
        vault_name=vault_name,
        vault_path=vault_path,
        session_id=session_id,
        event_buffer=event_buffer,
    )


async def start_queued_chat_stream_task(
    *,
    vault_name: str,
    vault_path: str,
    prompt: str,
    image_paths: list[str] | None,
    image_uploads: list[chat_executor.UploadedImageAttachment] | None,
    session_id: str,
    tools: list[str],
    model: str,
    thinking: chat_executor.ThinkingValue | None = None,
    context_template: str | None = None,
    event_buffer: ChatTaskEventBuffer | None = None,
) -> ChatStreamTaskStart:
    """Start a streaming chat task that waits behind earlier tasks in its session."""
    runtime = get_runtime_context()
    buffer = event_buffer or CHAT_TASK_EVENT_BUFFER
    task = await runtime.task_coordinator.create_queued_task(
        kind=ExecutionTaskKind.CHAT,
        scope=chat_session_scope(session_id),
        source=ExecutionTaskSource.API,
        label=chat_task_label(session_id),
        metadata={
            "vault": vault_name,
            "session_id": session_id,
            "streaming": True,
            "model": model,
            "tools": list(tools),
            "queued_by_session": True,
        },
    )

    async def _run() -> None:
        try:
            async with runtime.task_coordinator.track_existing_task(task.task_id) as tracked_task:
                await _wait_for_prior_chat_session_tasks(
                    task_id=tracked_task.task_id,
                    session_id=session_id,
                )
                prepared = await chat_executor._prepare_chat_execution(
                    vault_name=vault_name,
                    vault_path=vault_path,
                    prompt=prompt,
                    image_paths=image_paths,
                    image_uploads=image_uploads,
                    session_id=session_id,
                    tools=tools,
                    model=model,
                    thinking=thinking,
                    context_template=context_template,
                )
                await runtime.task_coordinator.mark_started(tracked_task.task_id)
                await _run_prepared_chat_stream_task(
                    task=tracked_task,
                    prepared=prepared,
                    vault_name=vault_name,
                    vault_path=vault_path,
                    session_id=session_id,
                    event_buffer=buffer,
                )
        except asyncio.CancelledError:
            await _append_cancelled_if_open(buffer, task.task_id)
            raise
        except Exception as exc:  # noqa: BLE001 - preflight failure is reported to subscribers
            if await _task_has_cancelled(task.task_id):
                await _append_cancelled_if_open(buffer, task.task_id)
                return
            await _publish_deferred_preflight_failure(
                task_id=task.task_id,
                exc=exc,
                vault_name=vault_name,
                session_id=session_id,
                prompt=prompt,
                tools=tools,
                model=model,
                context_template=context_template,
                event_buffer=buffer,
            )
            return

    background_task = asyncio.create_task(_run(), context=contextvars.Context())
    runtime.background_tasks.add(background_task)
    background_task.add_done_callback(runtime.background_tasks.discard)
    return ChatStreamTaskStart(task=task, session_id=session_id)


async def _task_has_cancelled(task_id: str) -> bool:
    runtime = get_runtime_context()
    snapshot = await runtime.task_coordinator.get_task(task_id)
    if snapshot is None:
        return True
    return snapshot.status == "cancelled" or snapshot.cancel_requested


async def _wait_for_prior_chat_session_tasks(*, task_id: str, session_id: str) -> None:
    """Hold a queued chat task until older tasks in the same session finish."""
    runtime = get_runtime_context()
    scope = chat_session_scope(session_id)

    while True:
        own_task = await runtime.task_coordinator.get_task(task_id)
        if own_task is None:
            raise asyncio.CancelledError
        if own_task.is_terminal:
            raise asyncio.CancelledError

        active_tasks = await runtime.task_coordinator.list_tasks(
            kind=ExecutionTaskKind.CHAT,
            scope=scope,
            include_terminal=False,
        )
        older_tasks = [
            task
            for task in active_tasks
            if task.task_id != task_id and task.created_at < own_task.created_at
        ]
        if not older_tasks:
            await runtime.task_coordinator.update_metadata(
                task_id,
                {
                    "queue_position": 0,
                    "waiting_for_task_id": None,
                },
            )
            return

        await runtime.task_coordinator.heartbeat(
            task_id,
            status="queued",
            metadata={
                "queue_position": len(older_tasks),
                "waiting_for_task_id": older_tasks[0].task_id,
            },
        )
        await asyncio.sleep(0.05)


async def _append_cancelled_if_open(
    event_buffer: ChatTaskEventBuffer,
    task_id: str,
) -> None:
    """Publish a cancellation terminal event unless the stream already closed."""
    if await event_buffer.is_terminal(task_id):
        return
    try:
        await event_buffer.append(
            task_id,
            "cancelled",
            {
                "event": "cancelled",
                "choices": [{
                    "delta": {},
                    "index": 0,
                    "finish_reason": "cancelled",
                }],
            },
        )
    except RuntimeError:
        return


@asynccontextmanager
async def _provided_execution_task(
    task: ExecutionTaskSnapshot,
) -> AsyncIterator[ExecutionTaskSnapshot]:
    yield task


async def _publish_deferred_preflight_failure(
    *,
    task_id: str,
    exc: Exception,
    vault_name: str,
    session_id: str,
    prompt: str,
    tools: list[str],
    model: str,
    context_template: str | None,
    event_buffer: ChatTaskEventBuffer,
) -> None:
    """Mark and publish a preflight failure from a deferred chat task."""
    runtime = get_runtime_context()
    workspace_path = _CHAT_STORE.get_session_workspace_path(session_id, vault_name)
    chat_executor._log_chat_failure(
        "Queued streaming chat preflight failed",
        vault_name=vault_name,
        session_id=session_id,
        model=model,
        tools=tools,
        streaming=True,
        phase="preflight",
        prompt_length=len(prompt),
        context_template=context_template,
        workspace_path=workspace_path,
        exc=exc,
    )
    if isinstance(exc, chat_executor.ChatContextTemplateError):
        payload = _error_event_data(f"\n\nTemplate error: {str(exc)}", exc.details)
    else:
        classification = classify_exception(exc, phase="preflight")
        payload = _error_event_data(
            "\n\nError: An unexpected error occurred",
            classification.to_metadata(),
        )
    await event_buffer.append(task_id, "error", payload)
    await runtime.task_coordinator.mark_failed(task_id, reason=f"{type(exc).__name__}: {exc}")


async def _run_prepared_chat_stream_task(
    *,
    task_id: str | None = None,
    task: ExecutionTaskSnapshot | None = None,
    prepared: chat_executor.PreparedChatExecution,
    vault_name: str,
    vault_path: str,
    session_id: str,
    event_buffer: ChatTaskEventBuffer,
) -> None:
    """Run a prepared streaming chat task and publish buffered task events."""
    runtime = get_runtime_context()
    if task is None and task_id is None:
        raise ValueError("Either task or task_id is required")
    task_context = (
        _provided_execution_task(task)
        if task is not None
        else runtime.task_coordinator.track_existing_task(str(task_id))
    )
    should_mark_started = task is None
    full_response = ""
    final_result = None
    tool_activity: dict[str, dict[str, Any]] = {}
    session_buffer_store = chat_executor.get_session_buffer_store(session_id)
    run_deps = chat_executor.ChatRunDeps(
        context_manager_now=chat_executor._resolve_context_manager_now(),
        buffer_store=session_buffer_store,
        buffer_store_registry={"session": session_buffer_store},
        session_id=session_id,
        vault_name=vault_name,
        message_history=list(prepared.message_history or []),
        tools=list(prepared.tools or []),
    )

    async with task_context as task:
        if should_mark_started:
            await runtime.task_coordinator.mark_started(task.task_id)
        async with chat_session_history_lock(session_id=session_id, vault_name=vault_name):
            _CHAT_STORE.add_messages(
                session_id,
                vault_name,
                [chat_executor._accepted_user_request(prepared)],
            )

        chat_executor._log_chat_lifecycle(
            "Streaming chat execution started",
            vault_name=vault_name,
            session_id=session_id,
            model=prepared.model,
            tools=prepared.tools,
            streaming=True,
            phase="agent_stream",
            prompt_length=len(prepared.prompt_for_history),
            attached_image_count=prepared.attached_image_count,
            context_template=prepared.context_template,
            workspace_path=prepared.workspace_path,
            extra={
                "history_message_count": len(prepared.message_history or []),
                "prompt_for_history_tokens": estimate_token_count(prepared.prompt_for_history),
                "task_id": task.task_id,
            },
        )

        try:
            async for event in prepared.agent.run_stream_events(
                prepared.user_prompt,
                message_history=prepared.message_history,
                deps=run_deps,
                usage_limits=chat_executor._chat_usage_limits(),
            ):
                if isinstance(event, PartStartEvent):
                    if isinstance(event.part, TextPart) and event.part.content:
                        delta_text = event.part.content
                        full_response += delta_text
                        await event_buffer.append(
                            task.task_id,
                            "delta",
                            _delta_event_data(delta_text),
                        )

                elif isinstance(event, PartDeltaEvent):
                    if isinstance(event.delta, TextPartDelta):
                        delta_text = event.delta.content_delta
                        full_response += delta_text
                        await event_buffer.append(
                            task.task_id,
                            "delta",
                            _delta_event_data(delta_text),
                        )

                elif isinstance(event, FunctionToolCallEvent):
                    await _publish_tool_call_started(
                        task_id=task.task_id,
                        event=event,
                        event_buffer=event_buffer,
                        tool_activity=tool_activity,
                        vault_name=vault_name,
                        session_id=session_id,
                    )

                elif isinstance(event, FunctionToolResultEvent):
                    await _publish_tool_call_finished(
                        task_id=task.task_id,
                        event=event,
                        event_buffer=event_buffer,
                        tool_activity=tool_activity,
                        vault_name=vault_name,
                        session_id=session_id,
                    )

                elif isinstance(event, AgentRunResultEvent):
                    final_result = event.result

            if final_result:
                async with chat_session_history_lock(
                    session_id=session_id,
                    vault_name=vault_name,
                ):
                    _CHAT_STORE.add_messages(
                        session_id,
                        vault_name,
                        chat_executor._messages_after_accepted_user_request(
                            final_result.new_messages()
                        ),
                    )
                    chat_executor._clear_latest_turn_failure(
                        session_id=session_id,
                        vault_name=vault_name,
                    )
                chat_executor._log_chat_lifecycle(
                    "Streaming chat execution completed",
                    vault_name=vault_name,
                    session_id=session_id,
                    model=prepared.model,
                    tools=prepared.tools,
                    streaming=True,
                    phase="session_persist",
                    prompt_length=len(prepared.prompt_for_history),
                    attached_image_count=prepared.attached_image_count,
                    context_template=prepared.context_template,
                    workspace_path=prepared.workspace_path,
                    extra={
                        **chat_executor._summarize_tool_activity(tool_activity),
                        "response_length": len(full_response),
                    },
                )

            await event_buffer.append(
                task.task_id,
                "done",
                {
                    "event": "done",
                    "choices": [{
                        "delta": {},
                        "index": 0,
                        "finish_reason": "stop",
                    }],
                    "tool_summary": tool_activity,
                },
            )

        except asyncio.CancelledError as exc:
            chat_executor._log_chat_failure(
                "Streaming chat execution cancelled",
                vault_name=vault_name,
                session_id=session_id,
                model=prepared.model,
                tools=prepared.tools,
                streaming=True,
                phase="agent_stream",
                prompt_length=len(prepared.prompt_for_history),
                attached_image_count=prepared.attached_image_count,
                context_template=prepared.context_template,
                workspace_path=prepared.workspace_path,
                extra=chat_executor._summarize_tool_activity(tool_activity),
                exc=exc,
            )
            await event_buffer.append(
                task.task_id,
                "cancelled",
                {
                    "event": "cancelled",
                    "choices": [{
                        "delta": {},
                        "index": 0,
                        "finish_reason": "cancelled",
                    }],
                },
            )
            raise
        except chat_executor.ChatCapabilityError as exc:
            chat_executor.logger.warning("Streaming capability mismatch", data=exc.details)
            chat_executor._record_latest_turn_failure(
                session_id=session_id,
                vault_name=vault_name,
                exc=exc,
                phase="agent_stream",
                streaming=True,
                model=prepared.model,
                tools=prepared.tools,
            )
            await event_buffer.append(
                task.task_id,
                "error",
                _error_event_data(f"\n\nError: {str(exc)}", exc.details),
            )
            raise
        except chat_executor.ContextTemplateExecutionError as exc:
            details = build_context_template_error_details(
                vault_name=vault_name,
                session_id=session_id,
                template_name=exc.template_name,
                phase=exc.phase,
                template_pointer=exc.template_pointer,
            )
            chat_executor.logger.warning(
                "Streaming context template execution failure",
                data=details | {"error": str(exc)},
            )
            chat_executor._record_latest_turn_failure(
                session_id=session_id,
                vault_name=vault_name,
                exc=exc,
                phase="agent_stream",
                streaming=True,
                model=prepared.model,
                tools=prepared.tools,
            )
            await event_buffer.append(
                task.task_id,
                "error",
                _error_event_data(f"\n\nTemplate error: {str(exc)}", details),
            )
            raise
        except chat_executor.ChatContextTemplateError as exc:
            chat_executor.logger.warning("Streaming context template failure", data=exc.details)
            chat_executor._record_latest_turn_failure(
                session_id=session_id,
                vault_name=vault_name,
                exc=exc,
                phase="agent_stream",
                streaming=True,
                model=prepared.model,
                tools=prepared.tools,
            )
            await event_buffer.append(
                task.task_id,
                "error",
                _error_event_data(f"\n\nTemplate error: {str(exc)}", exc.details),
            )
            raise
        except UsageLimitExceeded as exc:
            limit_error = chat_executor._build_chat_usage_limit_error(exc)
            chat_executor._log_chat_failure(
                f"Streaming chat {chat_executor._usage_limit_label(limit_error)} exceeded",
                vault_name=vault_name,
                session_id=session_id,
                model=prepared.model,
                tools=prepared.tools,
                streaming=True,
                phase="agent_stream",
                prompt_length=len(prepared.prompt_for_history),
                attached_image_count=prepared.attached_image_count,
                context_template=prepared.context_template,
                workspace_path=prepared.workspace_path,
                extra={
                    **chat_executor._summarize_tool_activity(tool_activity),
                    **limit_error.details,
                },
                exc=exc,
            )
            chat_executor._record_latest_turn_failure(
                session_id=session_id,
                vault_name=vault_name,
                exc=exc,
                phase="agent_stream",
                streaming=True,
                model=prepared.model,
                tools=prepared.tools,
            )
            await event_buffer.append(
                task.task_id,
                "error",
                _error_event_data(
                    (
                        f"\n\n{chat_executor._usage_limit_display_label(limit_error)} "
                        f"reached: {str(limit_error)}"
                    ),
                    limit_error.details,
                ),
            )
            raise limit_error from exc
        except Exception as exc:
            classification = classify_exception(exc, phase="agent_stream")
            _CHAT_TASK_FAILURES[task.task_id] = exc
            chat_executor._log_chat_failure(
                "Streaming chat execution failed",
                vault_name=vault_name,
                session_id=session_id,
                model=prepared.model,
                tools=prepared.tools,
                streaming=True,
                phase="agent_stream",
                prompt_length=len(prepared.prompt_for_history),
                attached_image_count=prepared.attached_image_count,
                context_template=prepared.context_template,
                workspace_path=prepared.workspace_path,
                extra=chat_executor._summarize_tool_activity(tool_activity),
                exc=exc,
            )
            chat_executor._record_latest_turn_failure(
                session_id=session_id,
                vault_name=vault_name,
                exc=exc,
                phase="agent_stream",
                streaming=True,
                model=prepared.model,
                tools=prepared.tools,
            )
            await event_buffer.append(
                task.task_id,
                "error",
                _error_event_data(
                    "\n\nError: An unexpected error occurred",
                    classification.to_metadata(),
                ),
            )
            raise

    if final_result:
        await chat_executor._try_auto_compact_after_turn(
            session_id=session_id,
            vault_name=vault_name,
            vault_path=vault_path,
        )


async def stream_chat_task_sse(
    *,
    task_id: str,
    event_buffer: ChatTaskEventBuffer | None = None,
    after_sequence: int = 0,
    keepalive_seconds: float = 15.0,
    raise_terminal_errors: bool = False,
) -> AsyncIterator[str]:
    """Stream buffered chat task events as SSE chunks."""
    buffer = event_buffer or CHAT_TASK_EVENT_BUFFER
    iterator = buffer.subscribe(task_id, after_sequence=after_sequence).__aiter__()
    pending_event: asyncio.Task[Any] | None = None
    try:
        while True:
            if pending_event is None:
                pending_event = asyncio.create_task(iterator.__anext__())
            try:
                event = await asyncio.wait_for(
                    asyncio.shield(pending_event),
                    timeout=keepalive_seconds,
                )
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            except StopAsyncIteration:
                pending_event = None
                return
            pending_event = None

            payload = dict(event.data)
            payload.setdefault("event", event.event)
            payload.setdefault("sequence", event.sequence)
            yield f"data: {json.dumps(payload)}\n\n"
            if (
                raise_terminal_errors
                and event.event == "error"
                and (failure := _CHAT_TASK_FAILURES.pop(task_id, None)) is not None
            ):
                raise failure
    finally:
        if pending_event is not None and not pending_event.done():
            pending_event.cancel()


def _delta_event_data(delta_text: str) -> dict[str, Any]:
    return {
        "event": "delta",
        "choices": [{
            "delta": {"content": delta_text},
            "index": 0,
            "finish_reason": None,
        }],
    }


def _error_event_data(message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "event": "error",
        "choices": [{
            "delta": {"content": message},
            "index": 0,
            "finish_reason": "error",
        }],
        "details": details,
    }


async def _publish_tool_call_started(
    *,
    task_id: str,
    event: FunctionToolCallEvent,
    event_buffer: ChatTaskEventBuffer,
    tool_activity: dict[str, dict[str, Any]],
    vault_name: str,
    session_id: str,
) -> None:
    tool_id = event.tool_call_id
    tool_part = getattr(event, "part", None)
    tool_name = getattr(tool_part, "tool_name", "tool")
    tool_args = None
    if tool_part is not None:
        try:
            tool_args = tool_part.args_as_json_str()
        except Exception as exc:  # noqa: BLE001 - defensive: upstream variations
            chat_executor.logger.debug(
                "args_as_json_str failed; using raw args",
                data={"error": str(exc)},
            )
            tool_args = tool_part.args
    tool_activity[tool_id] = {
        "tool_name": tool_name,
        "status": "running",
    }
    payload = {
        "event": "tool_call_started",
        "tool_call_id": tool_id,
        "tool_name": tool_name,
        "arguments": chat_executor._normalize_tool_args(tool_args),
    }
    if tool_name == "code_execution":
        payload["arguments_detail"] = chat_executor._normalize_tool_detail(tool_args)
    chat_executor.logger.set_sinks(["validation"]).info(
        "Streaming tool call started",
        data={
            "event": "chat_tool_call_started",
            "vault_name": vault_name,
            "session_id": session_id,
            "tool_call_id": tool_id,
            "tool_name": tool_name,
            "arguments_length": len(tool_args or ""),
            "memory_rss_bytes": chat_executor._get_process_rss_bytes(),
        },
    )
    await event_buffer.append(task_id, "tool_call_started", payload)


async def _publish_tool_call_finished(
    *,
    task_id: str,
    event: FunctionToolResultEvent,
    event_buffer: ChatTaskEventBuffer,
    tool_activity: dict[str, dict[str, Any]],
    vault_name: str,
    session_id: str,
) -> None:
    tool_id = event.tool_call_id
    result_part = getattr(event, "result", None)
    tool_name = getattr(result_part, "tool_name", "tool")
    result_content = None
    if result_part is not None:
        try:
            result_content = result_part.model_response_str()
        except Exception as exc:  # noqa: BLE001 - defensive fallback
            chat_executor.logger.debug(
                "model_response_str failed; using raw content",
                data={"error": str(exc)},
            )
            result_content = getattr(result_part, "content", None)
    tool_activity[tool_id] = {
        "tool_name": tool_name,
        "status": "completed",
    }
    payload = {
        "event": "tool_call_finished",
        "tool_call_id": tool_id,
        "tool_name": tool_name,
        "result": chat_executor._normalize_tool_result(result_content),
    }
    if tool_name == "code_execution":
        payload["result_detail"] = chat_executor._normalize_tool_detail(result_content)
    result_text = tool_result_as_text(result_content)
    chat_executor.logger.set_sinks(["validation"]).info(
        "Streaming tool call finished",
        data={
            "event": "chat_tool_call_finished",
            "vault_name": vault_name,
            "session_id": session_id,
            "tool_call_id": tool_id,
            "tool_name": tool_name,
            "result_length": len(result_text),
            "result_token_estimate": estimate_token_count(result_text) if result_text else 0,
            "memory_rss_bytes": chat_executor._get_process_rss_bytes(),
        },
    )
    await event_buffer.append(task_id, "tool_call_finished", payload)
