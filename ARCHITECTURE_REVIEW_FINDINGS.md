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

5. Medium: deferred preflight errors lose specific user-facing detail. Status: addressed in the current slice.
   - Deferred chat preflight now maps known chat capability, context-template, usage-limit, image attachment, and unsupported model-alias errors to stable SSE error payloads.
   - Unknown exceptions still use the generic unexpected-error message with structured classification metadata.

6. Low drift: generic execution-task UI controls live in workflow modules. Status: addressed in the current slice.
   - Generic stop/stop-all dashboard behavior now lives in `static/js/execution-tasks.js`.
   - Workflow actions remain scoped to workflow-specific execution and result rendering.

7. High: shutdown can trigger rollback before active tasks have actually stopped.
   - `TaskCoordinator.shutdown(...)` requests cancellation and immediately marks every active task `cancelled`.
   - Terminal observers run from that mark, including vault rollback.
   - `RuntimeContext.shutdown(...)` waits for background tasks only after rollback may already have fired.
   - Risk: rollback can run while a still-unwinding task continues to mutate files.
   - Fix direction: request cancellation first, wait for tracked handles/background tasks to settle, then mark only genuinely unfinished or handle-less tasks terminal.

8. Medium-high: expired chat event buffers can make SSE clients hang forever.
   - The chat task event endpoint verifies the task exists, then subscribes to the process-local event buffer.
   - If a terminal task still exists but its event stream has been pruned, `ChatTaskEventBuffer.subscribe(...)` creates a new empty stream and `stream_chat_task_sse(...)` keeps sending keepalives indefinitely.
   - Fix direction: distinguish not-yet-started streams from expired streams; return a terminal SSE error or HTTP 410 for known terminal tasks whose event buffer is no longer retained.

9. Medium security/reliability: chat multipart uploads are read fully before size limits apply.
   - The task API reads each multipart image fully into memory before creating `BinaryContent`.
   - Configured image byte limits are enforced later during chat preflight, after upload bytes are already resident.
   - Fix direction: enforce upload count and byte limits at the API boundary before task creation, preferably before or during file reads.

## Test Gaps

- Cancellation while a chat task is queued behind an earlier task. Status: covered in `validation/scenarios/integration/core/chat_task_session_queue.py`.
- Cancellation during deferred preflight before the task reaches agent streaming. Status: covered in `validation/scenarios/integration/core/chat_task_session_queue.py`.
