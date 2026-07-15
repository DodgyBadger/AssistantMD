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
Maintainers should run the full validation suite before merge.
