# Vault Activity Redesign Plan

## Objective

Make the Dashboard Vault Activity view a truthful, durable account of vault
changes initiated through AssistantMD while preserving the distinct roles of
execution tasks, mutation safety records, snapshots, and filesystem
observations. Direct Vault Explorer edits, creates, moves, and deletes must be
first-class activity without being represented as synthetic execution tasks.

## Current Boundaries

The current system has three separate records:

1. `TaskCoordinator` keeps process-local execution tasks for queueing,
   cancellation, timeouts, lifecycle events, and current-task context.
2. `task_file_mutations` durably records successful file mutations only when an
   execution task is active. Task snapshots support automatic rollback.
3. `vault_files` and `vault_file_events` record filesystem state observed by a
   vault refresh, regardless of who caused a change.

The Dashboard reads only `task_file_mutations`. Consequently:

- direct Vault Explorer file operations are absent;
- intentional direct operations are logged as `vault_state_mutation_untracked`;
- direct directory operations exist only in the rotating System Activity log;
- external or otherwise unattributed observations are absent;
- rolled-back task mutations remain visible without a durable rolled-back
  outcome;
- chat mutations are grouped by session, hiding individual turn/task outcomes;
- paired move rows inflate the displayed mutation count;
- a mutation's `event_sequence` is the latest sequence from a whole-vault
  refresh, not a guaranteed causal link to one observed event.

The System Activity log is operational diagnostics, not a suitable source for
Dashboard reconstruction: it rotates, has no relational query contract, and
mixes product activity with technical events.

## Design Principles

- Do not turn short synchronous Explorer commands into execution tasks.
- Keep execution tasks process-local and focused on runtime control.
- Persist user or system intent at mutation time; it cannot be reconstructed
  reliably from a later filesystem scan.
- Keep observed filesystem facts separate from attributed intent.
- Keep task rollback and snapshot policy explicit rather than applying it to
  every activity source.
- Preserve task, chat-session, workflow, goal, and step provenance for existing
  consumers such as session summaries and `goal_ops`.
- Represent a move as one logical operation even when rollback needs path-level
  before states for both source and destination.
- Treat task completion, failure, cancellation, timeout, and rollback as
  durable activity outcomes when file mutations occurred.

## Recommended Model

The vault-state subsystem remains the owner of the durable data. Add a generic
activity header and generalize mutation rows beneath it.

### `vault_activities`

One row represents one attributed unit of work within one vault:

- `activity_id`
- `vault_id`, `vault_name`
- `kind`: `chat`, `workflow`, `ingestion`, `explorer`, or `system`
- `source`: `api`, `scheduler`, `tool`, or `system`
- optional `task_id`, `task_scope`, chat session id, goal id, and step id
- user-facing label
- status: `running`, `completed`, `failed`, `cancelled`, `timed_out`,
  `rolled_back`, or `uncertain`
- created, updated, and completed timestamps
- retention timestamp and bounded metadata

Task-backed activities use the execution task id as provenance but remain
separate durable records. Explorer requests create an activity id directly and
complete it synchronously.

### Generalized mutation rows

Replace the task-only contract with activity-linked vault mutations. Each row
retains path-level before/after state and snapshot references needed by rollback
and existing artifact consumers. Add:

- `activity_id`
- `operation_id`, shared by paired rows for one logical move
- `target_kind`: `file` or `directory`
- operation outcome/status
- optional operation metadata, including directory descendant counts
- nullable task provenance through the owning activity

Task-backed mutation rows continue to carry the information required by
rollback, session summaries, and goal activity. Direct Explorer rows do not
require a task id.

### Mutation attribution context

Add a vault-state-owned context object independent of `ExecutionTaskSnapshot`.
The mutation layer derives it from the current execution task when one exists.
Direct API entrypoints establish it explicitly for the duration of one Explorer
command. Interactive application mutations should fail fast or emit an explicit
system attribution if neither context is supplied; `warn_without_task` should
not remain the normal control mechanism.

The task executor does not own this context. It only supplies task provenance
and terminal lifecycle notifications.

## Snapshot And Rollback Policy

Keep automatic rollback task-scoped. A task-backed activity captures its first
before-state snapshot per vault/path as it does today. Terminal observers update
the durable activity outcome after failure, cancellation, timeout, and rollback.

Direct Explorer actions retain pre-mutation file snapshots for revision history
without participating in automatic task rollback. This gives manual changes
made through AssistantMD the same retained file-state foundation as agent
changes while keeping Explorer commands synchronous and non-cancellable.
Files changed outside AssistantMD remain observable through vault refresh but
do not have guaranteed pre-state snapshots.

Directory moves remain one directory-level operation and do not create
per-descendant mutation or snapshot rows.

## Filesystem Observation

`vault_files` remains the rebuildable manifest and `vault_file_events` remains
the append-only observation feed. Do not infer user intent from these rows.

In a later slice, add refresh provenance:

- a refresh/batch id and reason (`bootstrap`, `mutation`, `manual`, or
  `scheduled`);
- optional `operation_id` correlation for expected paths and hashes;
- suppression of initial baseline scans from user-facing change history;
- grouping of otherwise unattributed events as **Observed changes**, not
  claimed external edits.

This should be a separate Dashboard view or filter from attributed **Actions**.
Combining both without provenance would duplicate internal changes and imply
causality the scanner does not know.

## Dashboard Contract

The first implementation slice should replace the task-only endpoint and UI
with attributed actions from `vault_activities`:

- one row per chat turn/task, workflow run, ingestion job, or Explorer command;
- source and outcome badges;
- logical operation count rather than raw path-row count;
- file and directory targets in details;
- snapshot links only where retained snapshots exist;
- rolled-back and uncertain outcomes shown explicitly.

Chat title remains useful labeling, but multiple chat turns should not be
collapsed into one lifetime session activity before their individual outcomes
are available. Optional grouping by session can be presentation behavior later.

A second slice can add an **Observed changes** view backed by refresh batches
and `vault_file_events`.

## Migration

Vault state declares its versioned schema migration through the centralized
system migration registry. The same migration runs during startup and through
the System UI migration action, with applied versions recorded in
`system/vault_state.db`.

1. Create the activity and generalized mutation schema without destroying the
   existing table.
2. Backfill one activity per existing task/vault and copy retained mutation
   rows, preserving task, goal, snapshot, and expiration references.
3. Give paired historical move rows a shared logical operation id when their
   reciprocal paths and task ids match.
4. Switch rollback, session summaries, goals, API models, and Dashboard queries
   to the generalized records.
5. Remove the old task-only table after backfill verification and update cleanup
   to retain activities, mutations, and snapshots according to their policies.

Legacy table mappings remain isolated inside the versioned migration module;
ordinary vault-state models and services contain only the current schema.

Rotating activity logs are not a reliable backfill source. Historical direct
Explorer actions before this schema will remain absent.

## Implementation Slices

### Slice 1: Durable Attributed Actions

- Add schema, models, migration, and activity context.
- Route task-backed file mutations into activities without changing task runner
  queueing or cancellation behavior.
- Route all Explorer mutations, including full-file save and directory move,
  through explicit `explorer` activities.
- Persist terminal and rollback outcomes for task-backed activities.
- Replace task-only activity API/UI contracts.
- Preserve session-summary and goal activity queries.

### Slice 2: Observation Provenance

- Add refresh ids/reasons and precise operation correlation.
- Expose observed change batches separately from attributed actions.
- Decide retention for observation batches and old `vault_file_events`.

### Slice 3: Manual Revisions And File History

- Generalize snapshot ownership so an Explorer activity can retain a file's
  pre-mutation state without a synthetic execution task.
- Capture one before-state per Explorer activity and path for create, edit,
  delete, and file move operations using existing snapshot retention.
- Add path-based revision history to the Vault Explorer file view, including
  activity source, timestamp, and snapshot preview.
- Restore retained file or absent states as new optimistic-concurrency-checked
  Explorer mutations, preserving the displaced current state as another
  revision.
- Keep rename lineage out of this slice. Move operations remain available in
  Vault Activity, while file history only follows the currently selected path.

### Slice 4: Explicit Activity Rollback

Add an explicit user action that restores every supported path in one durable
activity to its state before that activity began. This is separate from the
existing automatic task-failure rollback: it is initiated after completed work,
must protect changes made since that work, and must itself remain visible and
recoverable.

#### Restoration semantics

- Group mutations by exact vault-relative path and restore each path to the
  earliest retained before-state in the source activity. Do not replay every
  operation in reverse. This handles repeated edits, create-then-edit,
  delete-then-recreate, and paired file moves without redundant writes.
- Treat paired move rows as path-state changes sharing one logical operation.
  Build the complete desired path-state plan before touching the filesystem so
  move chains cannot fail because of transient source/destination collisions.
- Require retained payloads for every desired existing file. An expired or
  missing snapshot makes full rollback unavailable.
- In the first release, directory-level mutations make full activity rollback
  unavailable. Current directory records do not retain enough descendant state
  to promise a complete restoration. Do not silently perform a partial file-only
  rollback behind a **Rollback activity** action.
- Keep rollback exact-path scoped. Rename lineage and changes made outside the
  source activity are not inferred.

#### Preflight and concurrency

Add a vault-state rollback planner that returns the desired before-state and
expected current state for every affected path. The planner must verify that:

- the source activity belongs to the requested vault and has not already been
  rolled back;
- every mutation is supported and every required snapshot payload is readable;
- each path still matches the source activity's final existence and content
  hash, so later AssistantMD or external edits are not overwritten;
- no target path resolves outside the vault.

Execution repeats these checks while holding deterministic locks for the full
path set. Any conflict rejects the entire rollback before writes begin. Capture
all displaced current states before applying the plan. If a filesystem failure
occurs after writes begin, attempt compensation from those captures and report
an explicit uncertain outcome if compensation cannot restore every path.

#### Durable provenance

Execute a successful rollback as a new `explorer` activity rather than copying
snapshot files directly or rewriting the source mutation rows. The new activity:

- records one mutation per restored exact path through the shared vault mutation
  infrastructure;
- retains the displaced current states, making the rollback activity itself
  eligible for a later rollback when its preflight still passes;
- stores `source_activity_id` in activity metadata and uses a clear
  `Rollback: <source label>` label;
- finishes only after all path states are applied and the vault manifest is
  refreshed once.

Mark the source activity's `rollback_status` as `completed` only after the new
activity completes. Keep the source activity's original execution status; its
work completed even though a later user action reversed it. Disable repeated
rollback of that source activity and use the new rollback activity to reverse
the reversal.

Do not reuse `rollback_task_file_mutations()` for this path. Automatic failure
rollback remains task-lifecycle recovery and can use its existing first-state
snapshots. Explicit rollback needs optimistic concurrency, a multi-path plan,
new revision snapshots, and new activity provenance. Both paths may share small
snapshot-loading and desired-state helpers where that removes real duplication.

#### API and Dashboard

- Add a rollback preview endpoint for one vault activity. Return affected paths,
  restore/delete counts, conflicts, missing snapshots, unsupported operations,
  and `can_rollback` without changing files.
- Add an execution endpoint that includes the preview's expected path states;
  revalidate them under lock rather than trusting the client preview.
- Add **Rollback activity** to the Operations panel. Confirm with a concise path
  summary, disable the action with a specific reason when preflight fails, and
  refresh the activity list after success so the linked rollback activity is
  immediately visible.
- Keep single-revision restore and activity rollback as separate user actions,
  backed by the same lower-level exact-state restoration primitives rather than
  API calls between features.

## Validation Targets

Extend deterministic integration scenarios before implementation:

- `vault_file_reference_api`: Explorer edit/create/move/delete each creates one
  durable `explorer` activity; directory move has one logical operation.
- `vault_state_mutation_recorder`: task-backed mutations retain task, chat,
  workflow, goal, and snapshot provenance after migration.
- `vault_state_rollback`: failed/cancelled/timed-out task activity becomes
  `rolled_back` only after rollback completes and remains queryable accurately.
- session summary and goal scenarios: generalized mutation queries preserve
  current artifact and goal behavior.
- migration smoke test: existing task mutation rows backfill idempotently and
  historical paired moves count as one logical operation.
- activity rollback: multiple mutations to one file restore its first
  before-state exactly once.
- activity rollback: create-then-edit deletes the created file, while
  delete-then-recreate restores the original file.
- activity rollback: paired and chained file moves restore all exact path states
  without transient collisions.
- activity rollback: one stale path, missing snapshot, or directory mutation
  rejects the whole rollback and performs no writes.
- activity rollback: success creates a linked activity, preserves displaced
  states as revisions, refreshes the manifest once, and marks only the source
  activity's rollback status.
- activity rollback: a rollback activity can itself be rolled back when its
  expected current states still match.
- activity rollback: an injected mid-apply failure compensates already-written
  paths or persists an explicit uncertain outcome.

Maintainers should run the full validation suite after the focused scenarios
pass.

## Next Phase

Slice 1 is implemented on `dev/inline-editor`:

- `vault_activities` and `vault_mutations` own durable attributed activity;
- retained task mutation rows migrate idempotently and the legacy table is
  removed after backfill;
- task-backed mutations derive activity from execution context;
- Vault Explorer commands use explicit, lazily persisted `explorer` activity;
- terminal task and rollback outcomes are projected into the durable ledger;
- directory operations are recorded as one logical operation;
- automatic rollback remains snapshot-backed for files, and mixed file and
  directory failures report a partial rollback rather than a false full
  rollback;
- Dashboard, API, goal activity, session-summary artifacts, cleanup, and
  architecture docs use the generalized contract.

Slice 3 is implemented:

- snapshot ownership supports either an activity or an execution task;
- Explorer create, edit, delete, and file move operations retain pre-mutation
  file states under their durable activity;
- the unified file modal exposes exact-path revision history and previews;
- retained revisions can be restored without losing the displaced file state;
- revision history intentionally does not follow moved or renamed files.

Slice 2 observation provenance remains deferred.
Slice 4 explicit activity rollback is implemented:

- preview derives each exact path's earliest retained before-state and latest
  expected state;
- one conflict, missing snapshot, active activity, vault identity mismatch, or
  directory mutation rejects the complete rollback;
- execution revalidates expected states under deterministic multi-path locks;
- rollback uses one shared exact-state mutation primitive, captures displaced
  states, refreshes once, and records one linked Explorer activity;
- the Activity operations panel previews availability and confirms the atomic
  rollback action;
- rollback activities can themselves be rolled back when their expected states
  still match.

The focused activity rollback, revision restore, mutation recorder, and
automatic task rollback scenarios pass. Maintainers should still run the full
validation suite before merge.
