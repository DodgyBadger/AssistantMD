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

7. High: shutdown can trigger rollback before active tasks have actually stopped. Status: addressed in the current slice.
   - Runtime shutdown now requests cancellation, waits for runtime-owned background tasks to settle, then marks only remaining unfinished task records cancelled.
   - Terminal observers, including vault rollback, now run after the task coroutine has had a chance to handle cancellation cleanup.
   - Coverage: `validation/scenarios/integration/core/execution_task_runner.py`.

8. Medium-high: expired chat event buffers can make SSE clients hang forever. Status: addressed in the current slice.
   - `ChatTaskEventBuffer` now exposes retained-stream detection.
   - The chat task event endpoint returns HTTP 410 `ChatTaskEventsExpired` for known terminal chat tasks whose event stream has been pruned.
   - Coverage: `validation/scenarios/integration/core/chat_task_event_buffer.py` and `validation/scenarios/integration/core/chat_task_event_stream_api.py`.

9. Medium security/reliability: chat multipart uploads are read fully before size limits apply. Status: addressed in the current slice.
   - Multipart chat image uploads are now read in bounded chunks with per-image, image-count, and total-image-byte limits enforced at the API boundary.
   - Oversized uploads return HTTP 413 before an execution task is created.
   - Coverage: `validation/scenarios/integration/core/chat_multipart_upload_limits.py`.

## Test Gaps

- Cancellation while a chat task is queued behind an earlier task. Status: covered in `validation/scenarios/integration/core/chat_task_session_queue.py`.
- Cancellation during deferred preflight before the task reaches agent streaming. Status: covered in `validation/scenarios/integration/core/chat_task_session_queue.py`.
