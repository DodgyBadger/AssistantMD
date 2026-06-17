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

## Deferred Larger Fix

A more robust long-term design is a resumable chat task model where `/chat/execute`
starts or attaches to a process-local task and SSE subscribes to task events.
That would let work continue through client disconnects and allow reconnecting
to an active run. It is feasible but touches API contracts, UI state
rehydration, task event buffering, and transcript persistence, so it should be a
separate feature effort.
