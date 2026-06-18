# Architecture Review Findings

Reviewed after the task-owned chat execution refactor on `fix/delegation-errors`.

## Findings

1. High: queued chat cancellation can leave SSE subscribers hanging. Status: addressed in the current slice.
   - Queued chat work waits and preflights before attaching the asyncio handle to the `TaskCoordinator`.
   - `TaskCoordinator.cancel_task` marks queued tasks terminal immediately when no handle is attached.
   - If cancellation lands during queue wait or preflight, the task record can become `cancelled` without a terminal chat event in the event buffer.
   - Fix direction: attach the worker handle to the execution task before queue wait/preflight, or make the full queued lifecycle run inside one coordinator-tracked context.

2. High: chat background tasks are still spawned on the caller's current event loop. Status: addressed in the current slice.
   - Chat now starts background work through `ExecutionTaskRunner.start_background`.
   - The runtime bootstrap creates one `RuntimeBackgroundSpawner` and one `ExecutionTaskRunner`, then injects that runner into chat, workflow, and ingestion paths.
   - Workflow background starts also route through the shared runner, so chat and workflow no longer have separate background-spawn policy.
   - Direct `asyncio.create_task` usage for runtime work launch is centralized in `RuntimeBackgroundSpawner`; remaining direct usage is limited to subscriber/test helpers.

3. Medium: `_CHAT_TASK_FAILURES` can retain exception objects indefinitely. Status: addressed in the current slice.
   - The raw exception side channel was removed.
   - Chat task SSE now emits structured terminal error payloads without retaining exception objects after the task stream closes.

4. Medium security/reliability: surface adapter bypasses workspace path normalization. Status: addressed in the current slice.
   - Workspace path normalization now lives in `core.chat.workspace`.
   - API chat and external chat surfaces use the same vault-relative path normalization before storing session workspace metadata.

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
