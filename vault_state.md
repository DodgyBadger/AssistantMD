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
- `core/settings/settings.template.yaml`
  - Defines the existing `debug` setting. Vault state should reuse this setting
    for detailed per-file diagnostic/event emission rather than adding a
    separate detail flag in Slice 1.

Mutation paths are currently spread across tools and ingestion. Rollback will be
reliable only after known mutating paths route through a shared mutation
recorder.

New vault-mutating code should be enforceable by convention and CI:
tools/helpers should use `core.vault_state.file_mutations`, and
`scripts/check_vault_mutation_routing.py` should flag new direct
write/delete/move primitives outside approved legacy mutation files.

## Proposed Architecture

Add a neutral vault state subsystem, not tied to git or pending:

- `core/vault_state/models.py`
  - SQLAlchemy models for current file manifest, change events, task mutation
    records, and snapshot metadata.
- `core/vault_state/service.py`
  - Scan/refresh operations, path normalization, hashing, and manifest updates.
- `core/vault_state/mutations.py`
  - Shared helpers for recording file mutations and creating pre-mutation
    snapshots.
- `core/vault_state/file_mutations.py`
  - Paved API for vault file writes/deletes/moves. New tool/helper code that
    mutates vault files should call this layer rather than direct filesystem
    write primitives.
- `core/vault_state/rollback.py`
  - Restore/delete operations for task-scoped rollback.
- `core/vault_state/scanner.py`
  - Incremental filesystem walker for startup/manual/scheduled refresh.
- `core/vault_state/change_feed.py`
  - Cursor-based access to changed vault artifacts for downstream consumers
    such as pending diff, semantic indexing, or retrieval invalidation.
- `core/vault_state/identity.py`
  - Local vault identity resolver for `AssistantMD/vault.yaml`, mapping the
    current vault name/path to a stable `vault_id` for vault-state storage.

Add one declared system database:

```python
"vault_state": SystemDatabaseDefinition(
    name="vault_state",
    owner="core.vault_state",
    description="Rebuildable vault file manifest, task mutation records, and snapshot metadata.",
)
```

Initial tables:

- `vaults`
  - `vault_id`
  - `current_name`
  - `first_seen_at`
  - `last_seen_at`
  - `missing_since`
- `vault_files`
  - `vault_id`
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
- `vault_file_events`
  - `sequence`
  - `vault_id`
  - `vault_name`
  - `path`
  - `event_type`
  - `content_hash`
  - `observed_at`
  - compact metadata for changed/deleted/classification events
- `task_file_mutations`
  - `task_id`
  - `vault_id`
  - `vault_name`
  - `path`
  - `operation`
  - `event_sequence`
  - `before_exists`
  - `before_hash`
  - `before_snapshot_id`
  - `after_exists`
  - `after_hash`
  - `after_snapshot_id`
  - `snapshot_ref`
  - `created_at`
  - `expires_at`
- `snapshot_sets`
  - `id`
  - `task_id`
  - task identity fields (`task_kind`, `task_source`, `task_scope`, `task_label`)
  - `vault_id`
  - `vault_name`
  - `purpose`
  - scope fields (`scope_kind`, `scope_id`)
  - `snapshot_root`
  - `status`
  - `created_at`
  - `expires_at`
  - `rolled_back_at`
- `file_snapshots`
  - `id`
  - `snapshot_set_id`
  - `task_id`
  - `vault_id`
  - `vault_name`
  - `path`
  - `source`
  - `exists`
  - `content_hash`
  - `snapshot_ref`
  - `created_at`
  - `expires_at`

Snapshot files should live under `system/vault_snapshots/<snapshot_set_id>/`,
not inside the vault. Snapshot metadata should be explicit:
`snapshot_sets` records the moment/context that caused capture, and
`file_snapshots` records each file state captured at that moment. This should be
enough to restore existing files, delete new files, restore deleted files, and
support pending-diff baselines without pretending read baselines are mutations.

Task mutation rows are retention-bound task safety/audit state, not permanent
vault history. They should be retained long enough for rollback, conflict
inspection, and debugging, then removed by cleanup. Successful tasks, failed
tasks, cancelled tasks, and rolled-back tasks can all use the same retention
window initially. `task_snapshot_retention_days` should apply to both snapshot
metadata/files and `task_file_mutations`; storing `expires_at` on mutation rows
keeps cleanup explicit and allows later per-task policy changes.

Task mutation rows should link to the corresponding `vault_file_events.sequence`
through `event_sequence` when the mutation produced a vault-state event. This
keeps `vault_file_events` as the neutral vault change feed while preserving an
explicit bridge from task audit to vault history.

Vault-state tables should use `vault_id` as the durable vault namespace.
`vault_name` remains current alias/display metadata for logs, diagnostics, and
compatibility with the rest of the app. Slice 1 should not migrate existing
chat, workflow, scheduler, API, or authoring contracts away from `vault_name`.

`vault_id` should be stored inside the vault at `AssistantMD/vault.yaml` so it
survives folder or bind-mount renames. On first managed scan, create the file if
missing. On later scans, reuse the stored id and update the `vaults.current_name`
alias. If two discovered vault paths expose the same `vault_id`, treat that as a
configuration error and skip vault-state refresh for the duplicate until the
conflict is resolved.

Change sequencing should be monotonic within `vault_state.db` and exposed via a
small cursor API so downstream consumers can ask for "changes since sequence N"
without rescanning or rehashing vault files. The change feed should remain
artifact-neutral: it should describe file changes, not embedding, memory, or
retrieval policy.

Observed historical hashes should be derived from `vault_file_events` for now.
Do not add a separate deduped versions table until a concrete consumer needs a
compact `path + hash` inventory that cannot be served reasonably from events.

Excluded vault paths should be controlled by a settings-backed pattern list with
gitignore-style matching semantics. Generated and system-owned paths that are
not excluded should be classified separately from user-authored vault content.
In particular, `AssistantMD/Chat_Sessions/` contains derived transcript exports
in the current architecture, while canonical chat history lives in
`system/chat_sessions.db`. Derived exports should not become the default source
for future memory indexes.

## Settings

Start with conservative settings:

```yaml
vault_state_enabled: true
vault_state_excluded_patterns:
  - ".git/"
  - "**/.DS_Store"
  - "**/__pycache__/"
  - "AssistantMD/Chat_Sessions/"
task_rollback_enabled: true
task_snapshot_retention_days: 7
vault_scan_interval_seconds: null
```

Notes:

- `vault_state_enabled` controls manifest refresh.
- `vault_state_excluded_patterns` controls which vault-relative paths are not
  represented in the manifest or change feed. Matching should be gitignore-like:
  directory patterns can exclude whole subtrees, glob patterns can match files,
  and all matches are evaluated against normalized vault-relative paths.
- `task_rollback_enabled` controls snapshot creation around supported task
  mutations.
- Retention cleanup should never delete vault files, only system snapshots,
  snapshot metadata, and expired task mutation audit rows.
- Scheduled scanning should be deferred until startup/manual refresh behavior,
  latency, and log volume are reviewed.
- The existing `debug` setting should control detailed per-file diagnostic
  activity/API events outside validation. Summary refresh events should remain
  available without debug enabled.

## Slice 1: Vault Manifest Core

Implement current-file manifest refresh for one vault.

Behavior:

- Resolve or create `AssistantMD/vault.yaml` and register the stable `vault_id`
  in `vaults`.
- Walk vault files while applying `vault_state_excluded_patterns`.
- Classify observed paths by artifact class where useful:
  - `user_content`
  - `assistant_authoring`
  - `assistant_generated`
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
- Emit summary events by default. Emit per-file diagnostic activity/API detail
  only when `debug` is enabled; validation events may remain detailed when a
  scenario asserts per-file behavior.

Validation target:

- Add `validation/scenarios/integration/core/vault_state_manifest.py`.
- Create a vault with two markdown files and one excluded path.
- Refresh manifest.
- Modify one file, delete one file, add one file.
- Rename the vault folder or simulate the same vault under a new current name,
  refresh again, and assert rows remain associated with the same `vault_id`.
- Refresh again and assert changed/new/deleted counts, hashes, artifact classes,
  change sequences, current alias updates, and absence of excluded paths.

Feedback checkpoint:

- Confirm excluded/classified paths, event payloads, and change-feed shape are
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
- Store `expires_at` using `task_snapshot_retention_days`.
- Link the mutation row to the corresponding vault event via `event_sequence`
  when available.

Required task context:

- Add a lightweight current execution context variable for the active task
  snapshot or task id.
- `TaskCoordinator.track_current_task(...)` sets this context.
- Mutation recorder can associate file mutations with chat and workflow tasks
  without passing `task_id` through every tool signature.
- Keep this runtime primitive generic enough for future audit consumers such as
  memory/retrieval operations and post-turn maintenance.

Routing rule:

- New vault-mutating tools and authoring helpers must call
  `core.vault_state.file_mutations`.
- Existing mutation paths should be moved behind that API incrementally.
- A static CI routing guard should scan likely tool/helper/ingestion/API modules
  and fail if new direct mutation primitives are introduced outside the approved
  migration list.
- The routing guard should not blanket-allow `file_ops_safe` or
  `file_ops_unsafe`; only intentional exceptions such as directory creation
  should be allowlisted by function/call.

Validation target:

- Add or extend a scenario where a workflow writes one file.
- Assert `task_file_mutations` records the write with the workflow `task_id`.
- Assert manifest updates immediately after the write.
- Assert the mutation row has `expires_at` and `event_sequence`.
- Add a CI routing guard that prevents new direct vault mutation paths from
  bypassing the shared mutation API.

Feedback checkpoint:

- Confirm task association works for workflow and chat before expanding to more
  operations.

## Slice 3A: Mutation Observability

Expose the durable task mutation log in the app UI before adding rollback
controls.

Behavior:

- Persist task kind, source, scope, and label on `task_file_mutations` because
  the execution task coordinator is process-local.
- Add a read-only API for recent activity mutation groups by vault.
- Group direct chat mutations by chat session scope so one chat session shows a
  history of all retained file changes from that session.
- Keep workflow mutations grouped by individual workflow execution task, including
  workflows launched from chat.
- Show recent file mutation activity in the Workflows tab under the Vaults
  section.
- Keep this surface read-only: no rollback, diff viewer, or cleanup controls in
  this slice.
- Existing `vault_state.db` files should receive additive schema updates for
  task mutation metadata.

Validation target:

- Extend the mutation recorder scenario to call the task mutation API.
- Assert the response groups workflow mutations by task and direct chat
  mutations by chat session, including task metadata, operation, path, event
  sequence, and hashes.

Feedback checkpoint:

- Review whether the UI grouping and fields answer "what did this chat session
  or workflow run change?" before wiring additional mutators through the shared
  mutation API.

## Slice 3B: Mutation Coverage Expansion

Move the remaining file tool mutations behind `core.vault_state.file_mutations`
so Vault Activity is not limited to create/write operations.

Behavior:

- Route `file_ops_safe(append)` through the shared mutation recorder.
- Route `file_ops_safe(move)` through the shared mutation recorder as two file
  mutation rows: source path absent after move, destination path present after
  move.
- Route `file_ops_unsafe(edit_line)`, `replace_text`, `truncate`, `delete`, and
  `move_overwrite` through the shared mutation recorder.
- Keep directory creation out of task file mutation activity for now unless a
  later rollback design needs directory-level records.
- For overwrite moves, record both source and destination paths so later rollback
  design can reason about both affected files.
- Move and move-overwrite rows should carry `related_path` so the source row
  points at the destination and the destination row points back at the source.
  This preserves the simple two-row mutation model while making paired move
  rows explicit for the UI and future rollback logic.

Validation target:

- Extend the mutation recorder scenario so one workflow performs safe append,
  safe move, unsafe edit, replace, truncate, delete, and move-overwrite.
- Assert all routed operations appear in the task mutation API group with event
  sequences and pre-mutation snapshot references where applicable.
- Assert move and move-overwrite rows expose their paired `related_path` values
  in both persisted rows and the API response.

Feedback checkpoint:

- Review whether paired move rows plus `related_path` are sufficient before
  rollback APIs are added.

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

## Slice 5: Operation Coverage Expansion

After the `file_ops_safe(write)` vertical slice proves task association,
snapshot capture, and rollback semantics, expand mutation routing operation by
operation.

Behavior:

- Route remaining `file_ops_safe` mutations through `core.vault_state.file_mutations`:
  - `append`
  - `move`
  - `mkdir` if directory tracking or rollback needs it
- Route `file_ops_unsafe` mutations:
  - `edit_line`
  - `delete`
  - `replace_text`
  - `move_overwrite`
  - `truncate`
- Route ingestion vault writes/deletes.
- Keep explicit `vault_state_mutation_untracked` or unsupported-rollback
  warnings for any known mutation path not yet covered.
- Keep the CI routing guard updated so new mutation files do not bypass the
  shared mutation API.

Validation target:

- Add operation-specific scenarios for each newly routed mutator.
- Assert mutation rows, event links, manifest updates, and snapshot behavior for
  each supported operation.

Feedback checkpoint:

- Review operation-specific rollback semantics before making unsupported
  operations appear rollback-protected.

## Slice 6: Automatic Rollback On Failure Or Cancellation

Add rollback execution for failed/cancelled rollback-enabled tasks.

Behavior:

- Rollback is driven by execution task terminal state, not by script-authored
  cleanup code.
- Runtime bootstrap attaches vault rollback as a `TaskCoordinator` terminal
  observer so workflow and chat tasks use the same rollback trigger.
- Workflow execution must mirror returned workflow statuses onto the execution
  task record before rollback hooks run:
  - `completed` and `skipped` are successful terminal states.
  - `failed`, `cancelled`, and `timed_out` are rollback-triggering terminal
    states.
- If authored code catches its own errors and intentionally finishes
  `completed` or `skipped`, treat that as author intent and do not infer failure
  from file mutations alone.
- Rollback retry after a task has already been marked rolled back should be a
  no-op with an explicit `already_rolled_back` result.
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

- Assert workflow `finish(status="skipped")` produces a skipped execution task
  rather than a completed task.
- Add workflow scenario that writes a file, then fails.
- Assert created, appended, deleted, and moved files return to the pre-task
  state.
- Assert activity log and validation events show rollback.
- Add cancellation case if deterministic cancellation can be kept fast.

Feedback checkpoint:

- Confirm whether automatic rollback on failure feels right before applying it
  to chat.

## Slice 7: Chat Task Rollback

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
- Add chat failure validation with a tool-mediated file mutation before the
  failure.
- Assert rollback removes/restores the file.
- Assert user message history behavior from prior cancellation work remains
  unchanged.

Feedback checkpoint:

- Confirm cancellation semantics and user-facing messaging before adding manual
  rollback APIs.

## Slice 8: Code Execution Rollback Coverage

Validate that code execution inherits rollback coverage from the parent
execution task instead of becoming a separate rollback unit.

Behavior:

- `code_execution` does not receive raw filesystem access.
- File mutations caused by code execution through `file_ops_safe` or
  `file_ops_unsafe` should be recorded under the active chat or workflow task.
- If the parent chat or workflow task fails, is cancelled, or times out after
  those mutations, automatic task rollback should restore/delete affected files.

Validation target:

- Add a workflow or chat scenario where authored code invokes file mutation
  tools from a code execution path, then the parent task fails.
- Assert the recorded mutation rows use the parent task id.
- Assert automatic rollback restores the vault.

Feedback checkpoint:

- Confirm this covers the practical code execution risk before widening
  rollback semantics further.

## Slice 9: Manual Retention Cleanup

Expose manual cleanup for expired vault-state task safety artifacts before
adding scheduled cleanup.

Suggested endpoint:

```http
POST /api/vault-state/cleanup
```

Behavior:

- Delete expired `task_file_mutations` rows.
- Delete expired `snapshot_sets`, `file_snapshots`, and snapshot files.
- Never delete vault files.
- Return counts for deleted mutation rows, snapshot rows, and snapshot files.
- Surface the action as a small manual maintenance button in the system/admin UI
  before introducing automatic scheduled cleanup.

Validation target:

- Create expired and unexpired task mutation rows.
- Invoke cleanup API.
- Assert only expired rows are deleted.
- Assert vault files are untouched.

Feedback checkpoint:

- Review cleanup payload and UI placement before adding scheduled retention.

## Future Extension: Manual File Version Restore

Manual file version restore is out of scope for this branch.

Possible later direction:

- Treat manual recovery as file-level version restore, not primary task-level
  rollback.
- Let a user select a file, inspect retained prior states from task snapshots or
  mutation history, compare the current file with a selected prior version, and
  restore that file or save the prior version as a separate copy.
- Keep whole-task manual rollback as an optional admin/debug action only if a
  concrete use case appears.

## Slice 10: Pending Diff Without Git

Use vault manifest and retained snapshots to support "what changed since this
workflow processed the file?"

Behavior:

- When `pending_files(operation="complete", items=...)` marks a file complete,
  capture the current file state in a `snapshot_sets` row with
  `purpose="pending_complete"` and per-file `file_snapshots` rows with
  `source="pending_files.complete"`.
- Keep the `pending_files` interface unchanged. `pending_files(operation="get",
  items=...)` attaches per-item `metadata["pending_diff"]` when a retained
  processed baseline is available.
- Diff baseline is the workflow's last completed state for that path, not the
  latest AssistantMD mutation snapshot.
- Return a unified text diff plus enough metadata to identify unavailable
  baselines cleanly, including `snapshot_set_id`, `file_snapshot_id`,
  baseline hash, and current hash.
- Use the stable `vault_id` plus workflow id and vault-relative path when
  resolving the last completed baseline.

Validation target:

- Workflow processes a markdown checklist.
- User adds new checklist items.
- `pending_files(operation="get", ...)` returns diff metadata for pending items.
- Read-only workflow completion creates a processed baseline that later detects
  external edits from Obsidian/manual file changes.

Feedback checkpoint:

- Review whether unified diff text is sufficient before adding markdown-aware
  interpretation or selector options.

## Slice 11: Scheduled Refresh And Downstream Index Consumers

Add periodic reconciliation and prepare a neutral change feed for retrieval,
memory, and other indexing consumers.

Behavior:

- Add low-priority scheduled scan controlled by `vault_scan_interval_seconds`.
- Scan compares mtime/size first and hashes only candidates.
- Emit summary events, not per-file events unless validation or `debug` asks for
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

- Confirm scan performance and excluded-pattern defaults on realistic vaults.

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

Finish Slice 3A, then review the Vault Activity UI with real chat and workflow
runs. After that, continue routing the remaining vault mutators through
`core.vault_state.file_mutations` before adding rollback controls.
