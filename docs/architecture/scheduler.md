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
- Protect reserved non-workflow jobs (e.g. `ingestion-worker`).
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

The governor:

- registers a process-local workflow execution task
- serializes workflow execution by vault scope (`workflow_vault:<vault_name>`)
- skips overlapping workflow runs in the same vault with status `skipped`
- applies `workflow_task_timeout_seconds` when configured
- emits workflow lifecycle validation events

APScheduler remains responsible for schedule timing and persistence. The governor owns in-process concurrency and lifecycle policy for the actual workflow run.
