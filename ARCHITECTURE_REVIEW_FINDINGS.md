# Architecture Review Findings

Reviewed after the task-owned chat execution refactor on `fix/delegation-errors`.

## Findings

1. High: queued chat cancellation can leave SSE subscribers hanging. Status: addressed in the current slice.
   - Queued chat work waits and preflights before attaching the asyncio handle to the `TaskCoordinator`.
   - `TaskCoordinator.cancel_task` marks queued tasks terminal immediately when no handle is attached.
   - If cancellation lands during queue wait or preflight, the task record can become `cancelled` without a terminal chat event in the event buffer.
   - Fix direction: attach the worker handle to the execution task before queue wait/preflight, or make the full queued lifecycle run inside one coordinator-tracked context.

2. High: chat background tasks are still spawned on the caller's current event loop.
   - Chat uses direct `asyncio.create_task`, while workflow background work routes through the runtime background loop.
   - This is architectural drift and keeps chat work sensitive to request-loop/TestClient lifecycle behavior.
   - Fix direction: extract a shared runtime background spawner and use it for chat, workflow, compaction, ingestion, and similar long-running tasks.

3. Medium: `_CHAT_TASK_FAILURES` can retain exception objects indefinitely.
   - Generic stream failures store original exception objects.
   - The new task event route does not use `raise_terminal_errors=True`, so those exceptions may never be popped.
   - Fix direction: store lightweight failure metadata or tie cleanup to task/event-buffer terminal retention.

4. Medium security/reliability: surface adapter bypasses workspace path normalization.
   - Web chat normalizes vault-relative workspace paths.
   - The surface adapter writes `workspace_path` directly into `ChatStore`.
   - Fix direction: move workspace normalization into a core helper and require every chat surface to use it.

5. Medium: deferred preflight errors lose specific user-facing detail.
   - Queued chat preflight only special-cases template errors.
   - Other known chat preflight failures become a generic unexpected-error SSE payload.
   - Fix direction: map known chat preflight exception types to stable SSE error payloads.

6. Low drift: generic execution-task UI controls live in workflow modules.
   - Dashboard rendering is now generic, but stop/stop-all behavior is still in workflow action code.
   - Fix direction: extract or rename this into an execution-task controller once the core path is stable.

## Test Gaps

- Cancellation while a chat task is queued behind an earlier task. Status: covered in `validation/scenarios/integration/core/chat_task_session_queue.py`.
- Cancellation during deferred preflight before the task reaches agent streaming. Status: covered in `validation/scenarios/integration/core/chat_task_session_queue.py`.
- Failure-retention cleanup after `/api/chat/tasks` errors.
- Dashboard stop-all policy for mixed task kinds.
