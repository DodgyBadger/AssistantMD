# Database Layer Consolidation Plan

## Purpose

This plan covers issue [#36](https://github.com/DodgyBadger/AssistantMD/issues/36):

- consolidate store modules into a clearer centralized database layer
- reduce database-file ownership drift
- prevent further schema/table bleed while larger state work is still ahead

## Current Inventory

### Shared Helpers

- [database.py](/app/core/database.py)
  - provides:
    - `Base`
    - `get_system_database_path(...)`
    - `create_engine_from_system_db(...)`
    - `create_session_factory(...)`
  - currently does **not** encode DB ownership rules or provide a single registry of DB files

### Current DB-Backed Modules

- [store.py](/app/core/context/store.py)
  - raw `sqlite3`
  - owns `cache.db`
  - tables:
    - `context_step_cache`
    - `sessions`
    - `context_summaries`

- [file_state.py](/app/core/utils/file_state.py)
  - SQLAlchemy
  - owns `file_state.db`
  - table:
    - `processed_files`

- [jobs.py](/app/core/ingestion/jobs.py)
  - SQLAlchemy
  - owns `ingestion_jobs.db`
  - table:
    - `ingestion_jobs`

- [database.py](/app/core/scheduling/database.py)
  - APScheduler SQLAlchemy job store
  - owns `scheduler_jobs.db`

### Actual DB File Contents

Current observed contents under the active system root:

- `cache.db`
  - tables:
    - `context_step_cache`
    - `sessions`
    - `context_summaries`
  - appears aligned with intended ownership

- `file_state.db`
  - tables:
    - `processed_files`
  - previously contained a stray `ingestion_jobs` table from schema bleed
  - the orphaned `ingestion_jobs` table has now been removed

- `ingestion_jobs.db`
  - tables:
    - `ingestion_jobs`
  - appears aligned with intended ownership

- `scheduler_jobs.db`
  - tables:
    - `apscheduler_jobs`
  - appears aligned with intended ownership
  - should likely remain isolated unless there is an overwhelming operational reason to change it

## Current Problems

- DB names are repeated as ad hoc strings in subsystem modules
- DB ownership is implicit rather than declared in one place
- persistence access patterns are inconsistent:
  - raw `sqlite3`
  - SQLAlchemy engines/session factories
  - third-party APScheduler store creation
- there is no centralized inventory or validation for which DB file a table belongs in
- this makes future `state` work likely to add even more persistence drift

Confirmed recurrence mechanism:

- [file_state.py](/app/core/utils/file_state.py) had been calling unconstrained `Base.metadata.create_all(...)`
- because `IngestionJob` shares the same SQLAlchemy `Base`, that allowed `ingestion_jobs` to be created in `file_state.db`

## Current Status

Completed in this first slice:

- centralized declared system DB definitions in [database.py](/app/core/database.py)
- added one registry of known system DB files and intended owners:
  - `cache`
  - `file_state`
  - `ingestion_jobs`
  - `scheduler_jobs`
- added shared raw sqlite connection helper for declared system DBs
- rewired current DB-backed modules to use the centralized declarations/helpers rather than only free-form DB strings:
  - [store.py](/app/core/context/store.py)
  - [database.py](/app/core/scheduling/database.py)
  - [jobs.py](/app/core/ingestion/jobs.py)
  - [file_state.py](/app/core/utils/file_state.py)
- added explicit table-creation helper in [database.py](/app/core/database.py)
- eliminated the active recurrence path for schema bleed by making table creation explicit in:
  - [jobs.py](/app/core/ingestion/jobs.py)
  - [file_state.py](/app/core/utils/file_state.py)

Not done yet:

- table/content inventory per DB file
- migration/cleanup of misplaced tables
- consolidation of raw `sqlite3` vs SQLAlchemy patterns
- any DB-file merge

## First Safe Refactor

Do not solve all migration/schema issues in one pass.

The smallest safe consolidation slice is:

1. declare canonical system DB definitions in [database.py](/app/core/database.py)
2. centralize DB-name ownership there
3. add shared helpers for:
   - resolving a declared DB path
   - opening a raw sqlite connection by declared DB name
   - creating SQLAlchemy engines from declared DB names
4. migrate current modules to use the centralized declarations instead of free-form DB strings

This does **not** yet merge DB files or rewrite `context.store` to SQLAlchemy.

## Non-Goals For This Slice

- merging `cache.db` and `file_state.db`
- changing current table layouts
- moving APScheduler off its current DB store
- solving all observed historical schema bleed immediately
- introducing `state` storage in the same refactor

## Target Shape After This Slice

### Central Registry

`core/database.py` should become the source of truth for:

- known system DB names
- intended ownership/module
- path resolution helpers

Likely definitions:

- `cache`
- `file_state`
- `ingestion_jobs`
- `scheduler_jobs`

### Module Expectations

- subsystem modules should import declared DB handles/definitions rather than hardcoding names
- raw sqlite modules should use a common connection helper
- SQLAlchemy modules should use the same declared DB registry

## Validation Target

Targeted local checks after the refactor:

- `python -m compileall core`
- `ruff check core`

If runtime behavior is touched materially, follow up with a focused validation scenario later. For this first slice, correctness is primarily structural and import-level.

## Next Step After This Slice

Once DB ownership is centralized:

- inventory actual table contents in each DB file
- compare intended vs actual ownership
- decide what migration/cleanup is needed before `state` storage lands

Immediate follow-up recommendation:

- keep `file_state.db` limited to `processed_files`
- do not touch `scheduler_jobs.db` unless a later inventory reveals a concrete operational problem

That should happen before implementing the `state` backend adapter.
