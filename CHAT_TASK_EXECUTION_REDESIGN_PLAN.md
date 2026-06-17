# Chat Task Execution Redesign Plan

## Goal

Make streaming chat execution task-owned instead of request-owned, so long-running
Pydantic AI runs survive browser refreshes, proxy disconnects, and SSE reader
cancellation. Keep the implementation on Pydantic AI public interfaces:
`Agent.run(..., event_stream_handler=...)` or `Agent.run_stream_events(...)`.
Do not build the redesign around `Agent.iter(...)` or Pydantic graph internals.

## Current Findings

- `core/chat/executor.py` owns both chat execution and SSE formatting.
- Non-streaming chat calls `prepared.agent.run(...)` inside
  `TaskCoordinator.track_current_task(...)`.
- Streaming chat calls `prepared.agent.run_stream_events(...)` inside the SSE
  async generator. A producer queue now emits keepalive comments, but the
  Pydantic AI run is still cancelled when the request-side generator is
  cancelled.
- `/api/chat/execute` returns either JSON or a live `StreamingResponse`.
- The UI in `static/app.js` posts `/api/chat/execute` with `stream: true` and
  reads the response body directly.
- Chat stop uses `/api/chat/sessions/{session_id}/cancel`, which resolves the
  active `chat_session:<session_id>` task and cancels its task id.
- `TaskCoordinator` already supports queued tasks, attaching an asyncio handle
  later, cancellation, terminal history, metadata updates, and task polling.
- `WorkflowGovernor.start_workflow(...)` already follows the desired shape:
  create a queued task, schedule a background asyncio task, attach it through
  `track_existing_task(...)`, and return a task snapshot immediately.
- ADR 0004 intentionally makes execution tasks process-local rather than a
  durable job store. This plan keeps that contract.
- ADR 0014 centralizes workflow policy in a governor. Chat needs an equivalent
  execution service, but not workflow-specific vault lanes in the first slice.
- Pydantic AI 1.85.1 exposes the public APIs needed for this:
  `Agent.run(...)`, `Agent.run_stream_events(...)`, `Agent.run_stream(...)`,
  and `Agent.run(..., event_stream_handler=...)`. Durable execution packages
  exist, but adopting Temporal, Prefect, or DBOS is out of scope for this plan.

## Design Contract

Introduce a chat execution task service that owns the agent run and exposes
events to request handlers.

- A chat run has one `ExecutionTaskKind.CHAT` task id.
- The background task, not the SSE request, owns the Pydantic AI call.
- SSE clients subscribe to buffered chat task events by task id.
- Disconnecting an SSE subscriber does not cancel the chat task.
- Explicit cancellation through task id or chat session id still cancels the
  background task.
- Chat session persistence remains unchanged: persist the accepted user prompt
  before the agent run, persist assistant/tool messages only after final result,
  and record latest-turn failure on bounded failures.
- The first version remains process-local. Reconnect works only while the same
  process retains the task event buffer.
- The initial implementation does not queue new user prompts behind an active
  chat run. It only creates the execution surface that makes that possible later.

## Proposed Components

### Chat Task Service

Add a small service module, likely `core/chat/task_execution.py`.

Responsibilities:

- Prepare chat execution or return preflight errors before task creation when
  possible.
- Create a queued `ExecutionTaskKind.CHAT` task through `TaskCoordinator`.
- Schedule a background runner on `RuntimeContext.background_tasks`.
- Attach the runner to the queued task with `track_existing_task(...)`.
- Execute the Pydantic AI public streaming API and translate events into the
  existing SSE payload contract.
- Persist session history and latest-turn failure state exactly as
  `core/chat/executor.py` does today.
- Publish lifecycle, delta, tool, done, cancelled, and error events into an
  event buffer owned by the service.

### Chat Task Event Buffer

Add a process-local buffer abstraction, either in the new service module or as
`core/chat/task_events.py`.

Minimum contract:

- Append typed chat events with a monotonically increasing sequence number.
- Retain events per task until terminal plus a bounded history limit.
- Allow subscribers to stream events from `after_sequence`.
- Wake subscribers when new events arrive.
- Emit keepalive comments from the subscriber loop, not from the worker.
- Close subscribers cleanly when the task reaches a terminal event.

The payload can remain SSE-oriented initially to keep the slice narrow:

- `event`: existing event name (`delta`, `tool_call_started`,
  `tool_call_finished`, `done`, `cancelled`, `error`)
- `sequence`: event sequence
- `data`: existing JSON payload

### API Shape

Add task-oriented chat endpoints while keeping `/api/chat/execute` compatible
through the transition.

New narrow endpoints:

- `POST /api/chat/tasks`
  - Accepts the same request body/form fields as `/api/chat/execute`.
  - Starts a background chat task.
  - Returns `{session_id, task}`.
- `GET /api/chat/tasks/{task_id}/events?after_sequence=0`
  - Returns SSE from the process-local event buffer.
  - Sends `X-Session-ID` and `X-Task-ID` headers.
  - Emits keepalive comments while the task is running and idle.

Compatibility path:

- Keep `/api/chat/execute?stream=true` working.
- Internally, it may call the same start-and-subscribe service so old clients
  still receive the current SSE payloads.
- Non-streaming `/api/chat/execute` can remain on the existing
  `execute_chat_prompt(...)` path until the streaming redesign is stable.

### UI Shape

First UI slice should minimize visible behavior changes.

- Submit chat by starting a task.
- Store the active `task_id` alongside `session_id`.
- Subscribe to task events and render the existing event payloads.
- Stop response by cancelling the task id when available, falling back to
  session cancellation.
- Treat SSE disconnect as recoverable: poll task detail, then resubscribe from
  the last received sequence if the task is still non-terminal.

## Implementation Slices

### Slice 1: Event Buffer Unit

Status: implemented.

Scope:

- Add the in-memory chat task event buffer.
- Add focused tests for append, sequence ordering, replay from cursor,
  subscriber wakeup, terminal close, and bounded retention.

Validation:

- New focused integration or unit-style scenario under
  `validation/scenarios/integration/core/`.
- `python -m ruff check` on new files.
- `python -m compileall` on new files.

Completed validation:

- `python validation/run_validation.py run integration/core/chat_task_event_buffer`
- `python -m ruff check core/chat/task_events.py validation/scenarios/integration/core/chat_task_event_buffer.py`
- `python -m compileall core/chat/task_events.py validation/scenarios/integration/core/chat_task_event_buffer.py`

Risk:

- Low. No API or execution behavior changes.

### Slice 2: Background Streaming Worker

Scope:

- Add `start_chat_stream_task(...)` service.
- Move current streaming event translation from `_stream_prepared_chat_prompt`
  into a reusable worker function.
- Worker publishes events into the buffer instead of yielding directly.
- Worker uses `TaskCoordinator.create_queued_task(...)`,
  `track_existing_task(...)`, and `RuntimeContext.background_tasks`.
- Use Pydantic AI public API only. Prefer `run_stream_events(...)` first because
  the current code already handles those event types. Consider
  `run(..., event_stream_handler=...)` only if it simplifies result capture
  without changing behavior.

Validation:

- Fake delayed streaming agent completes after the initial HTTP caller stops
  consuming events.
- Task detail reaches `completed`.
- Session history includes the assistant result.
- Existing chat cancellation scenario still passes.

Risk:

- Medium. This touches session persistence and cancellation semantics.

### Slice 3: SSE Subscription Endpoint

Scope:

- Add `GET /api/chat/tasks/{task_id}/events`.
- Convert buffered events to current SSE chunks.
- Keep keepalive comments in the subscriber loop.
- Ensure disconnecting this endpoint only removes the subscriber and does not
  cancel the task.

Validation:

- Start a chat task with a fake idle agent.
- Open event stream, consume one keepalive, then close/cancel the subscriber.
- Assert the task remains active.
- Reopen with `after_sequence` and receive the terminal `done` event.

Risk:

- Medium. This is the core fix for request-owned cancellation.

### Slice 4: Compatible `/api/chat/execute` Streaming Path

Scope:

- Update `stream=true` handling to start a background chat task and immediately
  subscribe to its events.
- Preserve the current wire format for `delta`, tool, `done`, `cancelled`, and
  `error` chunks.
- Preserve `X-Session-ID`; add `X-Task-ID`.
- Keep preflight errors behaving as they do today.

Validation:

- Existing `chat_stream_keepalive`, `chat_stream_failure_logging`,
  `chat_usage_limits`, and `model_failure_classification` targeted scenarios.
- Add one scenario where the compatibility SSE consumer is cancelled and the
  task continues to terminal.

Risk:

- Medium. Existing UI depends on this endpoint.

### Slice 5: UI Task Subscription

Scope:

- Change `static/app.js` to use `POST /api/chat/tasks` plus
  `GET /api/chat/tasks/{task_id}/events` for streaming sends.
- Track `activeChatTaskId`.
- Stop by `POST /api/tasks/{task_id}/cancel` when a task id exists.
- On stream interruption, poll `/api/tasks/{task_id}` and reconnect if the task
  is still running.

Validation:

- Manual browser smoke test for send, stop, refresh/reconnect, and tool events.
- Existing API scenarios should remain stable because compatibility endpoint
  still exists.

Risk:

- Medium. UI state transitions are easy to regress.

### Slice 6: Queue New User Messages Behind Active Run

Scope:

- Decide the user-visible contract for submitting while a chat task is active.
- Add an in-memory per-session queue only after task-owned streaming is stable.
- Ensure queued prompts start only after the prior chat task reaches terminal.
- Reuse `chat_session_history_lock(...)` to preserve history order.

Validation:

- Submit two prompts to the same session while the first fake agent is blocked.
- Assert second task remains queued.
- Release first agent, assert second starts after first terminal and sees the
  completed history.

Risk:

- Higher. This changes product behavior and should remain separate from the
  cancellation fix.

### Slice 7: External Chat Surface Adapter Contract

Scope:

- Add this only after the core web chat UI uses task-owned execution reliably.
- Define a thin adapter contract for non-web chat surfaces such as Telegram,
  Discord, CLI, or other inbound message systems.
- Keep adapters outside Pydantic AI execution details. An adapter should map an
  inbound message to `vault_name`, `session_id`, prompt content, attachments,
  model, tools, and optional workspace/context fields, then start a chat task
  and observe task events.
- Define surface-owned policies for identity, authorization, rate limits,
  platform message size limits, attachment normalization, and cancellation
  commands.
- Reuse the same chat task service and event buffer used by the web UI.

Validation:

- Add a fake surface adapter scenario that submits a message, receives task
  events, and records the final response without using `/api/chat/execute`.
- Add a cancellation scenario that maps a fake surface stop command to task
  cancellation.
- Assert the resulting chat session history is identical to a comparable web
  chat task.

Risk:

- Medium to high. The execution foundation should be stable first; most risk is
  in identity mapping, authorization, rate limiting, and platform-specific
  message constraints rather than agent execution.

## Explicit Non-Goals

- No `Agent.iter(...)` execution driver in this plan.
- No dependency on Pydantic AI durable execution backends.
- No persistent job store for chat task events.
- No cross-process reconnect guarantee.
- No multi-worker coordination.
- No queued user messages in the first implementation slice.
- No Telegram, Discord, or other external chat integration before the core web
  chat UI is running on task-owned execution.

## Contract-Sensitive Areas

- `/api/chat/execute` response format and headers.
- SSE event names and JSON payload shape consumed by `static/app.js`.
- Chat session persistence, especially cancelled turns retaining only the user
  prompt.
- Latest-turn failure metadata for model/tool/usage failures.
- Vault mutation rollback through task terminal observers.
- Task lifecycle validation event names from `TaskCoordinator`.
- Process-local task history limit and memory retention.

## Next Phase

Move to Feature Development with Slice 1 only. Do not start the API or UI work
until the event buffer contract is tested independently.
