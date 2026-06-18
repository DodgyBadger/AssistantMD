# Delegation Cancellation Keepalive Plan

## Context

Recent Logfire traces show a streaming chat request cancelled while a `delegate`
tool call was still running. The delegate did not hit its own timeout or usage
limits:

- `delegate_started` logged `timeout_seconds: 0.0` and `max_tool_calls: 32`.
- The child run was waiting on an OpenAI `/responses` request when cancellation
  propagated.
- The parent task logged `execution_task_cancelled` with `cancel_requested:
  false`, so the in-app cancel endpoint was not the source.
- The stream had no user-visible chunks while the delegate was blocked, making
  an upstream idle timeout plausible.

## Proposed Scope

Implement a small streaming keepalive layer for chat SSE responses:

1. Run `prepared.agent.run_stream_events(...)` in an internal producer task.
2. Convert model/tool events to the existing SSE payloads and push them into an
   asyncio queue.
3. Let the response generator wait on the queue with a short timeout and emit a
   harmless keepalive SSE event or comment when no payload is ready.
4. Preserve existing explicit cancellation behavior: if the client disconnects
   or `/chat/sessions/{session_id}/cancel` cancels the task, the stream still
   terminates as cancelled and rollback still applies.
5. Add one validation event or deterministic test hook only if needed to assert
   keepalive behavior without coupling tests to model text.

## Implemented Outcome

- Streaming chat now runs agent event production behind an internal queue and
  emits `: keepalive` SSE comments while waiting for model/tool events.
- Existing SSE data events are preserved for deltas, tool calls, tool results,
  errors, cancellation, and completion.
- Explicit streaming cancellation still emits the `cancelled` SSE event and
  keeps task cancellation semantics intact.

## Affected Areas

- `core/chat/executor.py`: streaming execution loop and cancellation handling.
- `static/app.js`: only if a new keepalive event type is emitted instead of SSE
  comments.
- `validation/scenarios/integration/core/`: add or extend a streaming scenario
  with a fake delayed agent event source.
- `docs/architecture/chat-sessions.md`: document that streaming chat emits
  keepalives during idle model/tool waits.

## Validation Target

Add an integration scenario that uses a fake streaming agent which delays longer
than the keepalive interval before yielding a terminal result. Assert:

- the stream returns at least one keepalive chunk before completion;
- the final `done` event is still emitted;
- explicit cancellation still produces a cancelled task and rollback behavior
  remains covered by existing cancellation scenarios.

Maintainers should run the full validation suite. Agents should run only the
new or updated focused scenario plus local smoke checks.

Focused validation run during implementation:

- `python validation/run_validation.py run integration/core/chat_stream_keepalive`
- `python validation/run_validation.py run integration/core/chat_stream_failure_logging integration/core/chat_usage_limits integration/core/chat_cancellation`
- `python -m ruff check core/chat/executor.py validation/scenarios/integration/core/chat_stream_keepalive.py`
- `python -m compileall core/chat/executor.py validation/scenarios/integration/core/chat_stream_keepalive.py`

## Implemented Larger Fix

Chat now uses a task-owned execution model. `POST /api/chat/tasks` starts a
process-local task, and SSE clients subscribe to task events through
`GET /api/chat/tasks/{task_id}/events`. Work can continue through client
disconnects, and completed responses are available when the session is reloaded.

### Problem This Solves

The keepalive fix reduces idle-timeout cancellations, but it does not make chat
execution independent from the live browser/proxy connection. If the client
disconnects, reloads, sleeps, changes network, or an upstream closes the stream
for reasons unrelated to idleness, the current streaming request can still
cancel the underlying agent run.

The deeper fix changes ownership:

- the execution task owns the agent run;
- the SSE response observes the task;
- explicit user stop remains the only normal UI action that cancels the task.

### Target Architecture

1. `POST /api/chat/tasks` creates a chat execution task and starts the agent run
   in a background task managed by `TaskCoordinator`.
2. The task writes structured stream events into a bounded task-event buffer:
   deltas, tool starts, tool finishes, errors, cancellation, and completion.
3. The initial HTTP response returns `{session_id, task}` for a separate
   subscribe endpoint.
4. `GET /api/chat/tasks/{task_id}/events` streams buffered events from a cursor
   and then follows live events.
5. If an SSE client disconnects, only the subscriber stops. The agent task keeps
   running unless the user calls `/chat/sessions/{session_id}/cancel` or
   `/api/tasks/{task_id}/cancel`.
6. The UI stores `session_id`, `task_id`, and the last received event cursor so
   it can reconnect after refresh or transient network failure.
7. When the agent finishes, normal chat persistence still appends completed
   assistant messages to `chat_sessions.db`; failed/cancelled runs keep the
   existing recovery marker behavior.

### Contract Questions

- Event retention: task snapshots are process-local today. Reconnect support
  needs a bounded in-memory event buffer at minimum, and possibly persisted
  task-event rows if reconnect-after-restart matters.
- Partial assistant output: decide whether partial deltas are only UI state or
  also persisted as an incomplete assistant draft.
- Cursor shape: prefer a monotonic integer sequence per task event over
  timestamp-based replay.
- Backpressure: buffers need clear limits and overflow behavior for very long
  generations or disconnected clients.
- Completion cleanup: decide how long completed task event buffers remain
  available after terminal status.
- Rollback: failed/cancelled task rollback should remain tied to terminal task
  status, not subscriber disconnect.

### Likely Implementation Slices

1. Introduce a `TaskEventBuffer` service owned by `RuntimeContext`.
2. Refactor streaming chat execution so the agent run pushes existing SSE-shaped
   event payloads into the buffer instead of yielding directly to the HTTP
   response.
3. Add a subscriber generator that reads from the buffer with keepalives and a
   cursor.
4. Start chat through the task API and attach subscribers to the task event
   stream.
5. Add a reconnect endpoint or extend active-task/session APIs to expose the
   subscribe URL and latest cursor.
6. Update the frontend to reconnect to an active task after reload/session load
   and to keep using the explicit cancel endpoint for stop.
7. Document runtime limits and update validation scenarios.

### Validation Targets

- Start a streaming chat, disconnect the subscriber, and assert the task remains
  running.
- Reconnect with a cursor and assert missed tool/delta events replay in order.
- Explicit cancel still cancels the task and triggers rollback for task-scoped
  vault mutations.
- Completed runs persist final assistant messages exactly once even if multiple
  subscribers attach.
- Buffer overflow produces a deterministic recoverable error or requires a full
  session reload, depending on chosen contract.

### Risks

- This is a real API/UI contract change, not just an executor refactor.
- Process-local tasks still disappear on server restart unless event/task state
  becomes durable.
- Multiple subscribers must not duplicate persistence or mutate shared
  per-turn state.
- Partial-output UX needs careful treatment so users are not shown stale text as
  a completed answer.
