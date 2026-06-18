# Runtime Subsystem

Runtime is the backbone that wires configuration, scheduler, loaders, and shared services into one process-wide context.

## Primary code

- `core/runtime/bootstrap.py`
- `core/runtime/context.py`
- `core/runtime/state.py`
- `core/runtime/config.py`
- `core/runtime/reload_service.py`
- `core/runtime/execution_tasks.py`
- `core/runtime/workflow_governor.py`
- `core/system_migrations.py`

## Responsibilities

- Bootstrap app services from `RuntimeConfig`.
- Create and register global `RuntimeContext`.
- Manage scheduler lifecycle and workflow reload delegation.
- Track process-local execution tasks for chat, workflows, ingestion, and history compaction.
- Refresh vault-state manifests and attach task terminal observers for rollback.
- Coordinate workflow execution lanes by vault.
- Run registered system database migrations during startup.
- Track reload metadata (`last_config_reload`).
- Provide runtime summary/health context to API surfaces.

## Startup flow

1. Build `RuntimeConfig`.
2. `bootstrap_runtime(...)` seeds bootstrap roots, runs registered system database migrations, and validates config.
3. Initialize workflow loader, ingestion service/worker, scheduler/job store, task coordinator, task runner, and workflow governor.
4. Register global runtime context.
5. Sync workflows and reserved system jobs into the scheduler, then resume scheduler.
6. Start vault-state manifest refresh in the background so web startup is not blocked by a full vault scan.

## Runtime Context Access

Global runtime context helpers live in `core/runtime/state.py`:

- `set_runtime_context(...)`
- `get_runtime_context()`
- `has_runtime_context()`
- `clear_runtime_context()`

`RuntimeStateError` is raised when runtime access is attempted before bootstrap/context setup.

## Path Resolution Model

Path helpers in `core/runtime/paths.py`:

- `get_data_root()`
- `get_system_root()`

Resolution order:

1. Active runtime context (`RuntimeContext.config.*_root`)
2. Bootstrap roots from `set_bootstrap_roots(...)`
3. Otherwise fail fast (`RuntimeStateError`)

After bootstrap, runtime context is the source of truth for roots.

## Bootstrap Roots and Entrypoints

`main.py` sets bootstrap roots before importing path-sensitive modules:

- `resolve_bootstrap_data_root()`
- `resolve_bootstrap_system_root()`
- `set_bootstrap_roots(...)`

Custom scripts should do the same if they import settings/path-sensitive modules before starting runtime.

## RuntimeConfig Details

`RuntimeConfig` (`core/runtime/config.py`) defines:

- `data_root`
- `system_root`
- scheduler worker limits
- feature flags (`features`)

`RuntimeConfig.__post_init__` ensures required directories exist and validates worker/log-level settings.

## Reload and Runtime Metadata

Config reload is centralized in `core/runtime/reload_service.py`.

Reload behavior:

- refresh settings/model/config-status caches
- refresh logging configuration
- update `runtime.last_config_reload` when runtime exists
- return structured reload result used by API responses

## Execution Task Coordination

Runtime owns a process-local `TaskCoordinator`, `RuntimeBackgroundSpawner`,
`ExecutionTaskRunner`, and `WorkflowGovernor`.

`TaskCoordinator` tracks active and recently terminal work for API/UI visibility and cancellation. It records task kind, scope, source, label, timestamps, terminal reason, metadata, and lifecycle events. Runtime bootstrap attaches terminal observers for task-level follow-up policies such as vault mutation rollback. Observers run from terminal lifecycle transitions after live worker coroutines have unwound. See [Execution Tasks](execution-tasks.md) for the task contract and [Vault State](vault-state.md) for mutation rollback behavior.

`RuntimeBackgroundSpawner` schedules detached runtime work onto the runtime loop
and registers background handles in the runtime shutdown task set.

`ExecutionTaskRunner` provides the shared shell for creating queued execution
tasks, running detached work in the background, and wrapping awaited inline work
under `TaskCoordinator` ownership. It also owns keyed gates for runtime queueing
and lane serialization, and enforces task-spec timeouts. Scheduled ingestion
work uses this runner for detached job execution.

`WorkflowGovernor` is the policy layer for workflow runs. It queues workflow
execution per vault, optionally limits total concurrent workflows across vaults,
registers workflow tasks, supplies the configured workflow task timeout policy,
and logs workflow lifecycle events.

## Common Failure Modes

- Accessing `get_data_root()` / `get_system_root()` before setting bootstrap roots.
- Importing path-sensitive modules in scripts before runtime/bootstrap setup.
- Assuming env vars alone are authoritative after runtime starts.
