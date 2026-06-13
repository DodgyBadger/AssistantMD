# Execution Tasks Subsystem

Execution tasks are process-local runtime records for long-running or cancellable work. They provide API/UI visibility, cancellation handles, validation events, and task identity for vault mutation tracking across chat execution, workflow execution, ingestion jobs, code_execution, and chat history compaction.

## Primary code

- `core/runtime/execution_tasks.py` — task lifecycle model, scope helpers, cancellation results
- `core/runtime/workflow_governor.py` — workflow concurrency policy and workflow task lifecycle logging
- `core/ingestion/task_execution.py` — ingestion job task wrapper for API and scheduler paths
- `core/chat/executor.py` — chat task registration for streaming and non-streaming runs
- `core/chat/compaction.py` — automatic compaction task registration
- `api/services.py` — API adapters for task listing, detail, and cancellation

## Task model

`TaskCoordinator` stores active and recently terminal tasks in memory. It is part of `RuntimeContext` and is not a persistent job store.
Runtime bootstrap may attach terminal observers to the coordinator. Observers run after terminal lifecycle events and are used for process-local follow-up work such as vault mutation rollback.

Vault-state mutation rows store the task id, kind, source, scope, and label from the active execution task. Chat mutations are grouped by chat-session scope for user-facing activity views; workflow and ingestion mutations remain grouped by individual task run.

Each task snapshot includes:

- `task_id`
- `kind` (`chat`, `workflow`, `ingestion`, `history_compaction`)
- `scope` (`chat_session:<session_id>`, `workflow_vault:<vault_name>`, or `ingestion_vault:<vault_name>`)
- `source` (`api`, `scheduler`, `tool`, `system`)
- `label`
- lifecycle timestamps
- status, cancel flag, terminal reason, latest event
- task metadata

Long-running task metadata may include progress and recovery details such as heartbeat timestamps, heartbeat age, stale-heartbeat flags, queue/blocking reason, workflow result summaries, and structured `workflow_failure` metadata for failed or timed-out workflow runs.

Tasks may also carry optional `goal_id` and `step_id` metadata for work being tracked by `goal_ops`. Execution-task lifecycle validation events include those ids when present, and vault file mutation rows persist them so goal-related files can be derived from normal mutation provenance.

Task kind, source, scope, and label values are centralized in `core/runtime/execution_tasks.py`. Callers should use `ExecutionTaskKind`, `ExecutionTaskSource`, `chat_session_scope(...)`, `workflow_vault_scope(...)`, `ingestion_vault_scope(...)`, `chat_task_label(...)`, `ingestion_task_label(...)`, and `compaction_task_label(...)` rather than constructing those strings inline.

## Lifecycle

Tasks start through `TaskCoordinator.track_current_task(...)`.

Lifecycle statuses:

- `queued`
- `running`
- `completed`
- `failed`
- `cancelled`
- `timed_out`
- `skipped`

Terminal statuses remain queryable until the bounded terminal history is pruned.

## Cancellation

`TaskCoordinator.cancel_task(...)` returns `ExecutionTaskCancellationResult`, which contains the latest snapshot and whether cancellation was effective.

- Active tasks are marked `cancel_requested=True`, log `execution_task_cancel_requested`, and have their asyncio handle cancelled.
- Terminal tasks are not mutated. The coordinator logs `execution_task_cancel_ignored` with `ignored_reason="task_terminal"` and returns `effective=False`.
- Missing task IDs return `None`; API services translate that into a 404 response.

Chat session cancellation is scope-oriented at the API layer: `/api/chat/sessions/{session_id}/cancel` resolves the active `chat_session:<session_id>` task and cancels that task ID.

Manual workflow execution is task-oriented at the API layer: `/api/workflows/execute`
starts the workflow in the background and returns the created task snapshot.
Clients should poll `/api/tasks/{task_id}` for terminal status and call
`/api/tasks/{task_id}/cancel` to stop a running workflow. Terminal workflow
result details are attached to task metadata as `workflow_result` when available.
Failed or timed-out workflow terminal metadata also includes `workflow_failure`
when the governor can classify the failure.

## Observability

Execution task events use the validation sink and stable event names:

- `execution_task_created`
- `execution_task_started`
- `execution_task_cancel_requested`
- `execution_task_cancel_ignored`
- `execution_task_completed`
- `execution_task_failed`
- `execution_task_cancelled`
- `execution_task_timed_out`
- `execution_task_skipped`
- `workflow_task_heartbeat`

Payloads include task identity fields (`task_id`, `kind`, `scope`, `source`, `label`), status, cancellation state, and terminal reason. These events are part of the scenario validation surface.
