# Scheduler Subsystem

Scheduler keeps workflow execution aligned with current workflow templates while preserving job timing when possible.

## Primary code

- `core/scheduling/jobs.py`
- `core/scheduling/parser.py`
- `core/scheduling/triggers.py`
- `core/scheduling/database.py`
- `core/scheduling/job_history.py`
- `core/runtime/workflow_governor.py`
- `core/workflow_runs/`

## Responsibilities

- Persist APScheduler jobs in system DB-backed job store.
- Reconcile loaded workflows to scheduler jobs (create/update/replace/remove).
- Preserve timing state when only lightweight args change.
- Protect reserved system jobs.
- Dispatch workflow jobs through the runtime workflow governor.
- Persist workflow attempts and authoritative terminal outcomes.

## Cron Schedule Semantics

Workflow frontmatter accepts `schedule: "cron: MINUTE HOUR DOM MONTH DOW"` and
passes the expression to APScheduler 3.x. Use weekday names (`mon`, `tue`,
`wed`, `thu`, `fri`, `sat`, `sun`) for day-of-week schedules.

APScheduler 3.x numeric weekdays do not match standard cron: `0` is Monday and
`1` is Tuesday. Standard cron commonly treats `0` or `7` as Sunday and `1` as
Monday. The parser currently preserves APScheduler 3.x behavior for existing
schedules; `core/scheduling/parser.py` provides explicit conversion helpers for
code paths that need to present or prepare standard cron-compatible weekday
semantics.

## Sync behavior

During `setup_scheduler_jobs(...)`:

- **create**: new enabled workflow with schedule.
- **update**: same trigger/engine, update args and preserve timing.
- **replace**: trigger or workflow function changed.
- **remove**: workflow disabled/removed/schedule removed.

System Activity receives one compact sync summary containing counts and the
manual-reload decision. Per-workflow records and complete loaded/scheduled/
disabled arrays are validation-only. Meaningful create, replace, and remove
events remain individually searchable without repeating the full workflow set
on every synchronization.

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
- creates and finalizes durable workflow run history
- emits workflow lifecycle validation events

APScheduler remains responsible for schedule timing and persistence. Runtime
execution policy owns in-process task running mechanics for the actual workflow
run, while the governor owns workflow-specific result metadata, global workflow
concurrency policy, lifecycle logging, and durable run finalization.

## Workflow Run History

`workflow_runs.db` stores workflow attempts from scheduler, API, tool, and
system sources. The governor creates a queued row before lane waits, marks it
running when execution begins, and finalizes it with the workflow domain result.
Returned `failed` or `skipped` results remain those statuses even when
APScheduler reports that the Python job executed normally.

Scheduler events record a `missed` run when a scheduled invocation did not
execute. Dispatch errors that occur before the governor creates a run are also
recorded, using an idempotent scheduler event key.

Detailed terminal history is retained for 90 days and at most 500 runs per
workflow. The latest terminal outcome for a workflow is preserved beyond that
window. Active execution remains visible through process-local execution tasks;
the durable ledger is the historical outcome source.

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
events for system jobs. Workflow last-run fields come from durable workflow run
history and survive container restarts. Workflow job details also include
`last_run_id` and `last_run_source` when an outcome exists.
