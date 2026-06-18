# Scheduler Subsystem

Scheduler keeps workflow execution aligned with current workflow templates while preserving job timing when possible.

## Primary code

- `core/scheduling/jobs.py`
- `core/scheduling/parser.py`
- `core/scheduling/triggers.py`
- `core/scheduling/database.py`
- `core/runtime/workflow_governor.py`

## Responsibilities

- Persist APScheduler jobs in system DB-backed job store.
- Reconcile loaded workflows to scheduler jobs (create/update/replace/remove).
- Preserve timing state when only lightweight args change.
- Protect reserved system jobs.
- Dispatch workflow jobs through the runtime workflow governor.

## Sync behavior

During `setup_scheduler_jobs(...)`:

- **create**: new enabled workflow with schedule.
- **update**: same trigger/engine, update args and preserve timing.
- **replace**: trigger or workflow function changed.
- **remove**: workflow disabled/removed/schedule removed.

## Job args contract

Workflow jobs run with picklable lightweight args from `create_job_args(...)`:

- `global_id` (`vault/name`)
- minimal config (`data_root`)

This avoids heavy object serialization in persistent job storage.

## Workflow execution policy

Scheduled workflow jobs call `core/authoring/engine.py`, which delegates execution to `RuntimeContext.workflow_governor`.

The workflow governor:

- routes workflow tasks through `ExecutionTaskRunner`
- supplies the vault scope (`workflow_vault:<vault_name>`) used for runner
  serialization
- queues overlapping workflow runs in the same vault until the active workflow
  completes
- optionally limits total concurrent workflow executions across all vaults
- supplies `workflow_task_timeout_seconds` to the runner when configured
- emits workflow lifecycle validation events

APScheduler remains responsible for schedule timing and persistence. Runtime
execution policy owns in-process task running mechanics for the actual workflow
run, while the governor owns workflow-specific result metadata, global workflow
concurrency policy, and lifecycle logging.

`max_concurrent_workflows` in general settings controls global workflow
concurrency across vaults. `0` disables the global limit. The per-vault lane is
always active so workflows for one vault run sequentially.

## System Jobs

Built-in runtime jobs use explicit ids so they are distinguishable from
user-authored workflow jobs in `scheduler_jobs.db`:

| Job id | Name | Purpose |
| --- | --- | --- |
| `ingestion-worker` | `Ingestion worker` | Drains queued ingestion jobs. |
| `vault-state-refresh` | `Vault state refresh` | Periodically refreshes vault-state manifests when `vault_scan_interval_seconds` is positive. |

System job ids are reserved during workflow reconciliation. Workflow sync must
not remove them when user workflows are disabled, deleted, or rescheduled.

## Status Metadata

`GET /api/status` includes scheduler job details for both workflow jobs and
system jobs. Each job entry includes:

- `job_type` (`workflow` or `system`)
- `last_run_time`
- `last_status`
- `last_error`
- `next_run_time`

Last-run fields are process-local and are populated from APScheduler execution
events after the current app process starts. They are not persisted across
container restarts.
