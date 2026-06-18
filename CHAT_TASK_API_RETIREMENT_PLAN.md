# Chat Task API Plan

## Purpose

Make task-owned chat execution the only user-facing chat-turn path while keeping
direct `agent.run(...)` available for internal one-shot model work such as
compaction, delegate helpers, and workflow helpers.

## Current Contract

User-facing chat turns use one canonical backend contract:

- submit a turn with `POST /api/chat/tasks`
- observe progress with `GET /api/chat/tasks/{task_id}/events`
- poll/cancel with `/api/tasks/{task_id}` and `/api/tasks/{task_id}/cancel`
- cancel the active turn for a session with `/api/chat/sessions/{session_id}/cancel`

External chat surfaces, such as Telegram or Discord, should use the same backend
contract and adapt event consumption to the surface. They may stream deltas,
batch edits, or wait for the terminal event before sending a final response.

Internal non-chat model work may continue to use `agent.run(...)` when the
contract is a complete artifact rather than a chat turn.

## Invariants

- Chat turns remain persisted in the canonical chat store.
- Chat session queueing remains per `chat_session:<session_id>`.
- Chat task cancellation emits terminal task state and a terminal stream event.
- Tool-call and model-request usage limits produce structured failures.
- Image attachments, workspace path, context template, thinking, model, and tool
  selection are supported by `POST /api/chat/tasks`.
- Compaction, delegate, workflows, and other internal one-shot model calls keep
  their complete-result model-call behavior.

## Completed Slices

- Added validation helpers for canonical chat tasks.
- Migrated chat behavior scenarios to the task API.
- Removed the retired user-facing chat execution path and compatibility
  scheduling workaround.
- Updated architecture docs to describe the current task-owned chat contract.

## Validation

Focused validation run during implementation:

- `integration/core/api_endpoints`
- `integration/core/chat_task_event_stream_api`
- `integration/core/chat_task_session_queue`
- `integration/core/chat_stream_keepalive`
- `integration/core/chat_stream_failure_logging`
- `integration/core/chat_usage_limits`
- `integration/core/model_failure_classification`
- `integration/core/chat_cancellation`
- `integration/core/chat_failure_rollback`
- `integration/core/code_execution_rollback`
- `integration/core/code_execution`
- `integration/core/delegate_tool`
- `integration/core/session_ops_chat_tool`
- `integration/core/chat_session_persistence_contract`
