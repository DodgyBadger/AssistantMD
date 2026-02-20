# Runtime Subsystem

Runtime is the backbone that wires configuration, scheduler, loaders, and shared services into one process-wide context.

## Primary code

- `core/runtime/bootstrap.py`
- `core/runtime/context.py`
- `core/runtime/state.py`
- `core/runtime/config.py`
- `core/runtime/reload_service.py`

## Responsibilities

- Bootstrap app services from `RuntimeConfig`.
- Create and register global `RuntimeContext`.
- Manage scheduler lifecycle and workflow reload delegation.
- Track reload metadata (`last_config_reload`).
- Provide runtime summary/health context to API surfaces.

## Startup flow

1. Build `RuntimeConfig`.
2. `bootstrap_runtime(...)` seeds bootstrap roots and validates config.
3. Initialize workflow loader, ingestion service/worker, scheduler/job store.
4. Register global runtime context.
5. Sync workflows into scheduler jobs and resume scheduler.

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

## Common Failure Modes

- Accessing `get_data_root()` / `get_system_root()` before setting bootstrap roots.
- Importing path-sensitive modules in scripts before runtime/bootstrap setup.
- Assuming env vars alone are authoritative after runtime starts.
