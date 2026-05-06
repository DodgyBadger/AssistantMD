# Vault State And Task Rollback Implementation Plan

## Goal

Build a file-first vault state layer that supports task rollback, incremental
workflow processing, and downstream artifact/index consumers without depending
on git.

Files remain the source of truth. Manifest data is a rebuildable reflection of
observed file state, while task mutation and snapshot records are runtime audit
artifacts used for rollback and inspection. Snapshots are temporary task-safety
artifacts rather than canonical content.

## Design Principles

- Vault files are canonical.
- Manifest rows may be deleted and rebuilt from files.
- Task mutation and snapshot rows are task audit records; they may expire, but
  they cannot be fully reconstructed from the filesystem after the fact.
- If the database and filesystem disagree, the filesystem wins.
- Snapshot storage is used only for rollback or change-comparison features that
  need prior content.
- Rollback starts by covering AssistantMD-owned mutations, not arbitrary host
  edits made outside the app.
- Vault state is neutral infrastructure. It records artifact facts and changes;
  memory, retrieval, embeddings, and other indexers consume those facts through
  explicit downstream interfaces.
- Each implementation slice must produce observable activity or validation
  events so behavior can be reviewed before widening scope.

## Current Codebase Shape

Relevant existing surfaces:

- `core/runtime/execution_tasks.py`
  - Tracks process-local tasks with `task_id`, kind, scope, status, metadata, and validation/activity events.
  - Does not persist task records beyond process memory.
  - Does not currently expose a context variable for code that needs to
    associate side effects with the active task.
- `core/runtime/workflow_governor.py`
  - Wraps workflow execution in `TaskCoordinator.track_current_task(...)`.
  - Serializes workflow execution per vault.
- `core/chat/executor.py`
  - Wraps streaming chat execution in `TaskCoordinator.track_current_task(...)`.
  - Chat tasks use scope `chat_session:<session_id>` and include vault metadata.
- `core/utils/file_state.py`
  - Stores workflow processed-file hashes in `system/file_state.db`.
  - Supports `pending_files(...)` but does not store a central vault manifest or prior snapshots.
- `core/memory/service.py` and `core/tools/memory_ops.py`
  - Provide the current conversation-history memory broker and LLM-facing
    adapter.
  - Future vector/semantic memory should extend that broker and consume vault
    state changes rather than introducing a parallel file crawler.
- `core/tools/file_ops_safe.py`
  - Mutating operations: `write`, `append`, `move`, `mkdir`.
- `core/tools/file_ops_unsafe.py`
  - Mutating operations: `edit_line`, `delete`, `replace_text`, `move_overwrite`, `truncate`.
- `core/ingestion/storage.py` and `core/ingestion/service.py`
  - Write imported artifacts and clean up source files inside vaults.
- `core/database.py`
  - Declares system database ownership. New vault state tables should use a declared system DB.

Mutation paths are currently spread across tools and ingestion. Rollback will be
reliable only after known mutating paths route through a shared mutation
recorder.

## Proposed Architecture

Add a neutral vault state subsystem, not tied to git or pending:

- `core/vault_state/models.py`
  - SQLAlchemy models for current file manifest, observed file versions, task
    mutation records, and snapshot metadata.
- `core/vault_state/service.py`
  - Scan/refresh operations, path normalization, hashing, and manifest updates.
- `core/vault_state/mutations.py`
  - Shared helpers for recording file mutations and creating pre-mutation
    snapshots.
- `core/vault_state/rollback.py`
  - Restore/delete operations for task-scoped rollback.
- `core/vault_state/scanner.py`
  - Incremental filesystem walker for startup/manual/scheduled refresh.
- `core/vault_state/change_feed.py`
  - Cursor-based access to changed vault artifacts for downstream consumers
    such as pending diff, semantic indexing, or retrieval invalidation.

Add one declared system database:

```python
"vault_state": SystemDatabaseDefinition(
    name="vault_state",
    owner="core.vault_state",
    description="Rebuildable vault file manifest, task mutation records, and snapshot metadata.",
)
```

Initial tables:

- `vault_files`
  - `vault_name`
  - `path`
  - `artifact_class`
  - `size`
  - `mtime_ns`
  - `content_hash`
  - `kind`
  - `change_sequence`
  - `first_seen_at`
  - `last_seen_at`
  - `changed_at`
  - `deleted_at`
- `vault_file_versions`
  - `vault_name`
  - `path`
  - `content_hash`
  - `change_sequence`
  - `observed_at`
  - optional snapshot pointer later
- `vault_file_events`
  - `sequence`
  - `vault_name`
  - `path`
  - `event_type`
  - `content_hash`
  - `observed_at`
  - compact metadata for changed/deleted/classification events
- `task_file_mutations`
  - `task_id`
  - `vault_name`
  - `path`
  - `operation`
  - `before_exists`
  - `before_hash`
  - `after_exists`
  - `after_hash`
  - `snapshot_ref`
  - `created_at`
- `task_snapshots`
  - `task_id`
  - `vault_name`
  - `snapshot_root`
  - `status`
  - `created_at`
  - `expires_at`
  - `rolled_back_at`

Snapshot files should live under `system/task_snapshots/<task_id>/`, not inside
the vault. Snapshot metadata should be enough to restore existing files, delete
new files, and restore deleted files.

Change sequencing should be monotonic within `vault_state.db` and exposed via a
small cursor API so downstream consumers can ask for "changes since sequence N"
without rescanning or rehashing vault files. The change feed should remain
artifact-neutral: it should describe file changes, not embedding, memory, or
retrieval policy.

Generated and system-owned paths should either be ignored or classified
separately from user-authored vault content. In particular,
`AssistantMD/Chat_Sessions/` contains derived transcript exports in the current
architecture, while canonical chat history lives in `system/chat_sessions.db`.
Derived exports should not become the default source for future memory indexes.

## Settings

Start with conservative settings:

```yaml
vault_state_enabled: true
task_rollback_enabled: true
task_snapshot_retention_days: 7
vault_scan_interval_seconds: null
```

Notes:

- `vault_state_enabled` controls manifest refresh.
- `task_rollback_enabled` controls snapshot creation around supported task
  mutations.
- Retention cleanup should never delete vault files, only system snapshots and
  snapshot metadata.
- Scheduled scanning should be deferred until startup/manual refresh behavior,
  latency, and log volume are reviewed.

## Slice 1: Vault Manifest Core

Implement current-file manifest refresh for one vault.

Behavior:

- Walk vault files while excluding `.git`, `AssistantMD/Chat_Sessions` if needed
  for generated transcript noise, caches, and configured ignored directories.
- Classify observed paths by artifact class where useful:
  - `user_content`
  - `assistant_authoring`
  - `assistant_generated`
  - `ignored`
- Compare path, `mtime_ns`, and size before hashing.
- Hash only new or changed files.
- Mark missing files with `deleted_at`; do not hard-delete rows initially.
- Assign a monotonic `change_sequence` and append a `vault_file_events` row for
  created, changed, deleted, and classification-changing observations.
- Emit validation/activity events:
  - `vault_state_refresh_started`
  - `vault_state_file_changed`
  - `vault_state_file_deleted`
  - `vault_state_refresh_completed`

Validation target:

- Add `validation/scenarios/integration/core/vault_state_manifest.py`.
- Create a vault with two markdown files.
- Refresh manifest.
- Modify one file, delete one file, add one file.
- Refresh again and assert changed/new/deleted counts, hashes, artifact classes,
  and change sequences.

Feedback checkpoint:

- Confirm ignored/classified paths, event payloads, and change-feed shape are
  useful before adding task rollback.

## Slice 2: Startup And Manual Refresh

Wire manifest refresh into runtime startup and vault rescan without changing
chat/workflow behavior.

Behavior:

- On startup, refresh all discovered vaults when `vault_state_enabled` is true.
- On manual vault rescan, refresh discovered vaults after workflow discovery.
- Activity log should show summary counts per vault.
- Startup should remain resilient: manifest refresh failures are logged and do
  not prevent workflows from loading unless a later strict setting is added.

Validation target:

- Update `validation/scenarios/integration/system_startup.py`.
- Assert startup emits vault-state refresh events and activity-log entries.
- Assert restart catches filesystem changes made while the system was stopped.

Feedback checkpoint:

- Review startup log noise and scan latency before adding scheduled scans.

## Slice 3: Mutation Recorder Without Rollback

Introduce a shared mutation recorder and route one narrow mutation path through
it first.

Recommended first path:

- `file_ops_safe(operation="write")`

Behavior:

- Resolve the vault-relative path.
- Record a pre-mutation snapshot decision but do not restore anything yet.
- Update manifest after successful write.
- Attach mutation metadata to activity/validation events.

Required task context:

- Add a lightweight current execution context variable for the active task
  snapshot or task id.
- `TaskCoordinator.track_current_task(...)` sets this context.
- Mutation recorder can associate file mutations with chat and workflow tasks
  without passing `task_id` through every tool signature.
- Keep this runtime primitive generic enough for future audit consumers such as
  memory/retrieval operations and post-turn maintenance.

Validation target:

- Add or extend a scenario where a workflow writes one file.
- Assert `task_file_mutations` records the write with the workflow `task_id`.
- Assert manifest updates immediately after the write.

Feedback checkpoint:

- Confirm task association works for workflow and chat before expanding to more
  operations.

## Slice 4: Snapshot Capture

Create pre-mutation snapshots for supported mutations.

Supported first operations:

- create new file
- overwrite existing file
- append existing file
- delete file

Behavior:

- Before the first task mutation to a path, copy the original file to the task
  snapshot root, or record `before_exists=false`.
- Do not duplicate snapshots for repeated mutations to the same path in one
  task.
- Store path metadata in `task_file_mutations`.
- Activity/validation events:
  - `task_snapshot_created`
  - `task_file_snapshot_recorded`

Validation target:

- Scenario with a workflow that creates, appends, and deletes files.
- Assert snapshot files/metadata represent original state.
- Assert repeated writes to the same path create one pre-mutation snapshot.

Feedback checkpoint:

- Review snapshot directory layout and metadata before implementing restore.

## Slice 5: Automatic Rollback On Failure Or Cancellation

Add rollback execution for failed/cancelled rollback-enabled tasks.

Behavior:

- On task failure or cancellation, restore all recorded task mutations in reverse
  path order.
- Existing files restore from snapshot.
- New files are deleted.
- Deleted files are restored.
- Emit:
  - `task_rollback_started`
  - `task_rollback_file_restored`
  - `task_rollback_completed`
  - `task_rollback_failed`
- Leave snapshot files after rollback until retention cleanup so failures can be
  inspected.

Integration point:

- Start with `WorkflowGovernor.execute_workflow(...)` because workflow task
  boundaries are already centralized.
- Chat rollback can follow once workflow rollback behavior is reviewed.

Validation target:

- Add workflow scenario that writes a file, then fails.
- Assert the file system returns to the pre-task state.
- Assert activity log and validation events show rollback.
- Add cancellation case if deterministic cancellation can be kept fast.

Feedback checkpoint:

- Confirm whether automatic rollback on failure feels right before applying it
  to chat.

## Slice 6: Chat Task Rollback

Extend the same mutation tracking and rollback behavior to streaming chat tasks.

Behavior:

- Chat file mutations through `file_ops_safe` and `file_ops_unsafe` are recorded
  under the chat task id.
- If a chat task is cancelled or fails after mutating files, rollback restores
  supported mutations.
- Successful chat tasks keep their changes and snapshot metadata until retention
  cleanup or manual discard.

Validation target:

- Extend chat cancellation validation with a tool call that writes a file before
  cancellation.
- Assert rollback removes/restores the file.
- Assert user message history behavior from prior cancellation work remains
  unchanged.

Feedback checkpoint:

- Confirm cancellation semantics and user-facing messaging before adding manual
  rollback APIs.

## Slice 7: Manual Task Rollback API

Expose rollback for recently completed tasks while snapshots remain available.

Suggested endpoint:

```http
POST /api/tasks/{task_id}/rollback
```

Rules:

- Only tasks with retained snapshots are rollbackable.
- Refuse rollback if any affected file has changed since the task completed,
  unless a later explicit force path is added.
- Rollback should be idempotent: already rolled back returns a clear no-op
  result.

Validation target:

- Workflow succeeds and creates a file.
- API rollback restores previous state.
- Second rollback returns already-rolled-back/no-op.
- External edit after task completion blocks rollback.

Feedback checkpoint:

- Review API payload and UI affordance before adding frontend controls.

## Slice 8: Pending Diff Without Git

Use vault manifest and optional snapshots to support "what changed since this
workflow processed the file?"

Behavior:

- Extend processed-file state to store last processed hash per workflow/path.
- Optionally store a compact prior snapshot for processed markdown files.
- Add either:
  - `pending_files(operation="diff", items=...)`, or
  - a new helper such as `file_changes_since_processed(...)`.
- Return structured changed hunks or markdown-aware additions.

Validation target:

- Workflow processes a markdown checklist.
- User adds new checklist items.
- Pending diff returns only new entries or changed hunks.

Feedback checkpoint:

- Decide whether markdown-aware parsing is worth adding before generic line diff
  is expanded.

## Slice 9: Scheduled Refresh And Downstream Index Consumers

Add periodic reconciliation and prepare a neutral change feed for retrieval,
memory, and other indexing consumers.

Behavior:

- Add low-priority scheduled scan controlled by `vault_scan_interval_seconds`.
- Scan compares mtime/size first and hashes only candidates.
- Emit summary events, not per-file events unless validation/debug mode asks for
  detail.
- Expose changed-file records by `change_sequence` so downstream consumers can
  process changes since their last cursor.
- Downstream embedding, retrieval, or memory workers consume vault-state changes
  by hash/sequence. They do not live inside `core.vault_state`.

Validation target:

- Scenario or smoke test triggers the scanner manually rather than waiting for
  wall-clock schedule.
- Assert changed files are visible through the change-feed cursor API.

Feedback checkpoint:

- Confirm scan performance and ignored-path defaults on realistic vaults.

## Safety Invariants

- Rollback never writes outside the vault.
- Snapshot metadata uses vault-relative paths only.
- A task snapshots a file before the first supported mutation to that path.
- Unsupported mutation paths must log that rollback is unavailable rather than
  pretending the task is protected.
- System snapshot cleanup never touches vault files.
- Manifest refresh failures do not delete user content.
- Full validation remains maintainer-owned; agents should run targeted scenarios
  only.

## Recommended Next Step

Start with Slice 1 only:

1. Add the `vault_state` system database declaration.
2. Implement manifest refresh for one vault, including artifact classification
   and monotonic change sequencing.
3. Add the first change-feed query for changes since a sequence cursor.
4. Add `validation/scenarios/integration/core/vault_state_manifest.py`.
5. Emit clear validation/activity events for changed, deleted, classified, and
   completed refresh results.

Do not start rollback until the manifest contract, classification rules,
change-feed cursor shape, and event payloads have been reviewed.
