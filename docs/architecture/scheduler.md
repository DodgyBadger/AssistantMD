# Scheduler Subsystem

Scheduler keeps workflow execution aligned with current workflow templates while preserving job timing when possible.

## Primary code

- `core/scheduling/jobs.py`
- `core/scheduling/parser.py`
- `core/scheduling/triggers.py`
- `core/scheduling/database.py`

## Responsibilities

- Persist APScheduler jobs in system DB-backed job store.
- Reconcile loaded workflows to scheduler jobs (create/update/replace/remove).
- Preserve timing state when only lightweight args change.
- Protect reserved non-workflow jobs (e.g. `ingestion-worker`).

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
