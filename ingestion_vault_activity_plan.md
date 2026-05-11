# Ingestion Vault Activity Plan

## Scope

Make ingestion-generated vault files visible in Vault Activity by ensuring import
jobs run inside the same execution task context used by other recorded vault
mutations.

## Affected Areas

- `core/runtime/execution_tasks.py`
  - Add an `ingestion` task kind and stable ingestion scope/label helpers.
- `api/services.py` and `api/endpoints.py`
  - Process inline import jobs under ingestion execution task context.
- `core/ingestion/task_execution.py`
  - Centralize the task-aware ingestion job wrapper for API and scheduler paths.
- `core/ingestion/worker.py`
  - Process queued scheduler jobs under ingestion execution task context.
- `validation/scenarios/integration/core/import_pipeline_core.py`
  - Assert imported output and source cleanup appear in the retained task
    mutation activity API.

## Contract

- PDF import output writes should create `task_file_mutations` rows with
  `task_kind="ingestion"` and `task_source="api"` for inline import scans.
- Source cleanup deletes should be recorded in the same ingestion activity
  group when the source is inside the vault.
- Existing manifest refresh behavior remains unchanged.
- Full validation remains maintainer-owned; this effort uses the targeted import
  pipeline scenario.

## Validation Target

Run the targeted `import_pipeline_core` validation scenario or, if the harness is
too heavy locally, run focused compile/smoke checks and request maintainer
scenario results.
