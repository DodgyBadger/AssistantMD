# Vault State Subsystem

Vault state maintains a durable, rebuildable view of vault files and a retained safety log for task-scoped file mutations.

## Primary Code

- `core/vault_state/service.py` — manifest refresh, change-feed events, task-mutation listing
- `core/vault_state/models.py` — SQLite models stored in `system/vault_state.db`
- `core/vault_state/identity.py` — stable vault id management through `AssistantMD/vault.yaml`
- `core/vault_state/file_mutations.py` — shared mutation API for tracked vault writes
- `core/vault_state/snapshots.py` — snapshot-set and file-snapshot capture
- `core/vault_state/rollback.py` — automatic rollback for failed, cancelled, and timed-out tasks
- `core/vault_state/cleanup.py` — retained snapshot and mutation cleanup

## Storage Model

Vault state uses `system/vault_state.db` plus retained snapshot files under `system/vault_snapshots/`.

The database tables have distinct roles:

| Table | Role |
| --- | --- |
| `vaults` | Stable vault id registry and current vault name |
| `vault_files` | Current observed file state per vault-relative path, including rows marked deleted |
| `vault_file_events` | Monotonic change feed of created, changed, classified, and deleted file observations |
| `snapshot_sets` | Execution-scoped moments when one or more file snapshots were captured |
| `file_snapshots` | Per-file snapshot records inside a snapshot set |
| `task_file_mutations` | Task-scoped audit rows for attempted vault file mutations |

`vault_files` is the current manifest. `vault_file_events` is append-only change history. `snapshot_sets` records why and when AssistantMD captured one or more file states. `file_snapshots` records the actual per-file state captured in that set. `task_file_mutations` records what a chat, workflow, or code_execution task attempted to change, including before/after hashes and a pointer to the relevant pre-mutation file snapshot.

## Vault Identity

Vault state uses a stable `vault_id` stored in `AssistantMD/vault.yaml`. The current vault folder name is still recorded as `vault_name`, but the id lets vault state keep a durable identity if a vault folder is renamed and rediscovered.

When vault state first sees a vault without metadata, it creates `AssistantMD/vault.yaml` with a generated `vault_id`.

## Manifest Refresh

`VaultStateService.refresh_vault(...)` scans one vault and updates `vault_files` and `vault_file_events`.

Refresh behavior:

- honors `vault_state_enabled`
- applies `vault_state_excluded_patterns` using gitignore-style matching
- hashes files when size, mtime, deletion state, or artifact class indicates a possible change
- classifies files as `user_content`, `assistant_authoring`, or `assistant_generated`
- emits validation events for refresh start/completion and per-file changes

Runtime bootstrap starts a background `refresh_all_vaults(...)` for discovered
vaults after the web runtime is available. File mutations routed through the
shared mutation API refresh the affected vault after the write.

When `vault_scan_interval_seconds` is positive, runtime registers a reserved
APScheduler system job:

- job id: `vault-state-refresh`
- name: `Vault state refresh`

The job periodically calls `refresh_all_vaults(...)` so external vault edits
from Obsidian or other tools are observed without requiring app restart or
manual rescan. Setting `vault_scan_interval_seconds` to `0` disables and removes
the scheduled job.

## Mutation Routing

Vault file writes should route through `core.vault_state.file_mutations` so they can be observed, snapshotted, and rolled back consistently.

Currently tracked mutation helpers include:

- `write_vault_file(...)`
- `write_vault_file_bytes(...)`
- `append_vault_file(...)`
- `replace_vault_file_content(...)`
- `delete_vault_file(...)`
- `move_vault_file(...)`

`file_ops_safe`, `file_ops_unsafe`, and ingestion output storage use this shared API for supported file mutations. The CI guard `scripts/check_vault_mutation_routing.py` scans core tool/helper/API/ingestion code for direct mutation primitives and fails when new writable paths bypass the shared mutation API, except for explicit allowlisted cases.

If no execution task is active, the mutation still performs the file operation and refreshes vault state. Task-less calls log `vault_state_mutation_untracked` unless the caller marks the write as an intentional system-service mutation, such as ingestion storage.

Unexpected failures in the shared mutation path emit `vault_state_mutation_failed`
with task context, vault identity, path, operation, stage, before-state metadata,
and error details before the exception propagates to the caller.

## Snapshot Sets

When a mutation runs inside an active execution task, vault state captures the original file state once per task/vault/path before the first mutation to that path.

Snapshot behavior:

- one `snapshot_sets` row represents the rollback capture point for the task/vault
- one `file_snapshots` row represents each captured path in that set
- existing files are copied under `system/vault_snapshots/<snapshot_set_id>/task_mutation_before/files/<vault-relative-path>`
- new files record a `file_snapshots` row with `exists=false` and no file payload
- the first `task_file_mutations` row for a task/path carries `before_snapshot_id` and the retained `snapshot_ref`
- later mutations to the same path in the same task reuse the first file snapshot
- expiration is computed from `task_snapshot_retention_days`

Snapshot sets also support processed baselines for `pending_files(...)`. When a workflow marks pending items complete, `pending_files` captures the current file contents in a `snapshot_sets` row with `purpose="pending_complete"` and per-file rows with `source="pending_files.complete"`. Later `pending_files(operation="get", ...)` calls can attach diff metadata for pending files by comparing the current file to the workflow's last completed baseline.

Snapshots support automatic rollback and pending-file diffs. They are not a full version-control system.

## Automatic Rollback

Runtime bootstrap registers `handle_task_terminal_for_rollback(...)` as a `TaskCoordinator` terminal observer.

Rollback runs when a task reaches one of:

- `failed`
- `cancelled`
- `timed_out`

Rollback behavior:

- obeys `task_rollback_enabled`
- groups mutation rows by vault/path
- restores the retained pre-mutation snapshot when the file existed before the task
- deletes files that were created by the task
- refreshes each affected vault after rollback
- marks rollback snapshot sets as `rolled_back`
- treats repeated rollback attempts as skipped with `already_rolled_back`

Rollback failures are logged as `task_rollback_failed`; they do not replace the original task terminal status.

## Observability

The Workflows tab shows recent task file mutation activity per vault through:

- `GET /api/vaults/{vault_name}/task-mutations`

The API groups chat mutations by chat session scope so multiple file writes in the same chat session appear as one user-facing activity. Workflow runs remain separate activities. The UI lists activity summaries first and opens the file-level mutations on demand.

The Configuration / Misc cleanup button calls:

- `POST /api/vault-state/cleanup`

Cleanup deletes expired `task_file_mutations`, expired `snapshot_sets`, expired `file_snapshots`, and managed snapshot files under `system/vault_snapshots/`. It does not delete vault files.

## Settings

Vault-state behavior is controlled by general settings in `system/settings.yaml`:

- `vault_state_enabled`
- `vault_state_excluded_patterns`
- `vault_scan_interval_seconds`
- `task_rollback_enabled`
- `task_snapshot_retention_days`

Startup background refresh, mutation-triggered refresh, manual rescan, and
scheduled refresh are active observation paths.
