# Chat Compaction Checkpoint Implementation Plan

## Scope

Refactor chat history compaction so it no longer destructively rewrites
`chat_messages`. Compaction should append a checkpoint record and all existing
public/runtime history consumers should continue to see the same compacted
effective history by default.

This plan focuses on:

- checkpoint persistence
- compaction write semantics
- effective-history reconstruction
- existing history consumers
- validation and contract docs

Session-summary stale detection and summary snapshotting are intentionally left
to the final section as follow-up work.

## Current Contract And Invariants

Current implementation:

- `core/chat/compaction.py::compact_chat_history` reads
  `ChatStore.get_history(...)`, generates a system summary message, builds
  `[summary, *recent_messages]`, then calls
  `ChatStore.replace_session_messages(...)`.
- `ChatStore.replace_session_messages(...)` deletes all existing
  `chat_messages` rows for the session and reinserts the replacement sequence.
- `ChatStore.get_history(...)` and `get_stored_messages(...)` return all rows
  from `chat_messages` ordered by `sequence_index`.
- The chat executor passes `ChatStore.get_history(...)` directly to the model.
- API session detail, transcript export, `retrieve_history(...)`,
  `assemble_context(...)`, `session_ops` summarization, and deep session search
  read through `get_stored_messages(...)` or `ChatHistoryService`.

Refactor invariants:

- Raw rows in `chat_messages` must remain append-only during compaction.
- Default `ChatStore.get_history(...)` must return effective replay history:
  latest checkpoint replacement plus raw messages after that checkpoint.
- Default `ChatStore.get_stored_messages(...)` must also return effective
  replay rows so API details, exports, Monty helpers, and search behavior remain
  user-compatible.
- Explicit raw/archival access may be added internally, but no public API should
  switch to raw history by accident.
- Existing sessions with no checkpoint should behave exactly as they do today.
- Multiple compactions must use the latest checkpoint only.
- Recent tool call/result pair preservation must keep working.
- Compaction API response shape and `chat_history_compact` tool result shape
  must not change.

## Persistence Design

Add `chat_compaction_checkpoints` to `system/chat_sessions.db` in
`core/chat/schema.py` through the existing SQLite migration runner in
`core/database_migrations.py`. Do not rebuild `system/chat_sessions.db` from
scratch.

`core/chat/schema.py` should follow the production pattern already used by
`core/memory/schema.py`:

- import `SQLiteMigration` and `apply_sqlite_migrations`
- define `MIGRATION_NAMESPACE = "chat_sessions"`
- define `CHAT_SESSION_MIGRATIONS`
- call `apply_sqlite_migrations(...)` from `ensure_chat_sessions_schema(...)`
  after the base tables/indexes exist

The first chat-session migration should add the checkpoint table and indexes:

```sql
CREATE TABLE IF NOT EXISTS chat_compaction_checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    checkpoint_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    vault_name TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    source TEXT NOT NULL,
    message_count_before INTEGER NOT NULL,
    last_message_sequence_index INTEGER NOT NULL,
    summary_message_json TEXT NOT NULL,
    replacement_history_json TEXT NOT NULL,
    metadata_json TEXT,
    UNIQUE (checkpoint_id),
    FOREIGN KEY (session_id, vault_name)
        REFERENCES chat_sessions(session_id, vault_name)
        ON DELETE CASCADE
)
```

Indexes:

- `(session_id, vault_name, id)` for latest-checkpoint lookup.
- `(session_id, vault_name, last_message_sequence_index)` for effective replay.

For fresh databases, the migration creates the same table after the current
base schema is bootstrapped. For existing databases, the migration records its
version in the target database's `schema_migrations` table and leaves existing
chat/session/message rows intact.

Use `replacement_history_json` as the authoritative effective prefix for the
checkpoint. This preserves exact current behavior even if later summary-message
formatting or recent-slice logic changes. `summary_message_json` remains useful
for inspection and future archival tooling.

## Store API Plan

Introduce an internal history mode type:

- `"effective"`: latest checkpoint replacement plus raw rows after the
  checkpoint.
- `"raw"`: all persisted `chat_messages` rows.

Keep existing call signatures default-compatible:

- `ChatStore.get_history(session_id, vault_name, *, mode="effective")`
- `ChatStore.get_stored_messages(session_id, vault_name, *, limit=None, mode="effective")`
- `ChatStore.get_message_count(session_id, vault_name, *, mode="effective")`
- `ChatStore.get_recent(session_id, vault_name, limit, *, mode="effective")`

Add checkpoint helpers:

- `get_latest_compaction_checkpoint(session_id, vault_name)`
- `add_compaction_checkpoint(...)`
- `get_highest_message_sequence_index(session_id, vault_name)`

Implementation details:

- Reuse existing `StoredChatMessage` for effective replay rows.
- For checkpoint replacement rows, synthesize `StoredChatMessage` instances from
  `replacement_history_json`.
- Preserve replacement sequence indices as `0..n-1` for effective-history
  compatibility. Raw rows after the checkpoint keep their raw `sequence_index`.
  This means sequence indices in effective history may jump after the
  replacement prefix; consumers already treat them as metadata rather than a
  dense contract.
- Apply `limit` after effective reconstruction so callers get the last N
  effective messages, not raw rows.
- Keep `replace_session_messages(...)` for any non-compaction callers or
  compatibility tests, but compaction should stop using it.

## Compaction Write Plan

Update `compact_chat_history(...)`:

1. Read current effective history through `chat_store.get_history(...)`.
2. Split effective history into older and recent slices.
3. Optionally export the current effective transcript before compaction.
4. Generate the summary message and replacement history.
5. Read the current highest raw `sequence_index`.
6. Insert one checkpoint with:
   - `checkpoint_id` equal to the existing `compaction_id`
   - `last_message_sequence_index` equal to the raw high-water mark
   - `summary_message_json`
   - full `replacement_history_json`
   - metadata containing current response/audit fields
7. Update session metadata under `last_compaction`.
8. Do not delete or insert any `chat_messages` rows.

`messages_before`, `messages_after`, token estimates, `kept_recent`, and
`summary_message_index` should continue to describe effective history, matching
today's API/tool behavior.

## Consumer Update Plan

Consumers that should remain on effective history by default:

- `core/chat/executor.py`: `message_history = _CHAT_STORE.get_history(...)`
- `core/chat/compaction.py`: status and compaction source history
- `api/services.py::get_chat_session_detail`
- `core/chat/transcript_writer.py`
- `core/chat/history_service.py::SQLiteConversationHistoryProvider`
- `core/authoring/helpers/history/retrieve.py` through `ChatHistoryService`
- `core/tools/session_ops.py`:
  - `summarize_session`
  - deep transcript search
  - list message counts until summary stale logic is updated separately

Internal raw access should initially be used only in:

- checkpoint creation high-water mark lookup
- validation assertions proving raw rows were retained
- future explicit archival/debug features

No public API parameter for raw history should be added in this pass.

## Validation Target

Extend `validation/scenarios/integration/core/chat_history_compaction.py`.

New deterministic assertions:

- Before compaction, raw/effective message counts are both six.
- After compaction, API response still reports:
  - `messages_before == 6`
  - `messages_after == 4`
  - `kept_recent == 3`
- Raw `chat_messages` still contains the original six rows.
- Effective `get_stored_messages(...)` returns four rows:
  - summary marker at index 0
  - preserved tool call
  - preserved tool result
  - final assistant response
- `ChatStore.get_history(...)` returns the same four effective model messages.
- Session detail endpoint returns four effective messages, preserving the
  current UI/API contract.
- A second compaction uses the latest checkpoint and does not resurrect older
  raw rows into effective history.
- Appending a new raw turn after compaction makes effective history equal:
  latest checkpoint replacement plus the appended raw turn.
- `retrieve_history(scope="session", limit="all")` sees effective history only.
- The checkpoint migration is recorded in `schema_migrations` for namespace
  `chat_sessions` and does not remove existing rows.

Optional smoke tests while implementing:

- Direct isolated `ChatStore` test against a temp system root for checkpoint
  insert/replay/limit behavior.
- Direct migration smoke test with a pre-existing `chat_sessions.db` containing
  `chat_sessions` and `chat_messages`, then call `ensure_chat_sessions_schema`
  and assert the checkpoint table exists and original rows remain.
- `python -m py_compile core/chat/schema.py core/chat/chat_store.py core/chat/compaction.py`

Per project guidance, agents should run targeted local smoke tests or the single
scenario only. Maintainers own the full validation run.

## Event Contract

Keep existing compaction events:

- `chat_compaction_started`
- `chat_compaction_plan_selected`
- `chat_compaction_completed`
- `chat_compaction_failed`

Add fields to existing event payloads rather than creating noisy new events:

- `history_mode: "effective"` on plan/completed events.
- `raw_messages_preserved: true` on completed event.
- `checkpoint_id` and `last_message_sequence_index` on completed event.

These fields document the behavioral decision without changing event names.

## Documentation Updates

Update current-contract docs only:

- `docs/architecture/chat-sessions.md`
  - describe `chat_compaction_checkpoints`
  - describe effective vs raw history
  - state that normal loading, API detail, transcript export, and helpers use
    effective history by default
- `docs/architecture/session-summaries.md`
  - update history broker wording to effective persisted history
  - leave stale-summary caveat as current behavior/follow-up, not migration
    guidance
- `docs/tools/chat_history_compact.md`
  - remove wording that compaction rewrites canonical chat history
  - say it records a checkpoint that makes future default history start with a
    system-maintained summary plus recent turns

Avoid documenting old behavior as a migration narrative in product docs.

## Risks And Mitigations

- **Risk:** a consumer accidentally sees raw archival history.
  **Mitigation:** default store APIs to effective mode and make raw mode
  explicit/internal.
- **Risk:** replacement history loses provider-native fidelity.
  **Mitigation:** serialize the complete `ModelMessage` list in
  `replacement_history_json` with the existing `TypeAdapter(ModelMessage)`.
- **Risk:** `limit` semantics drift after compaction.
  **Mitigation:** reconstruct effective history first, then slice.
- **Risk:** sequence-index metadata is no longer dense after appended
  post-checkpoint turns.
  **Mitigation:** preserve dense indices for checkpoint replacement rows and raw
  indices for appended rows; do not expose sequence density as a contract.
- **Risk:** transcript export before compaction changes content.
  **Mitigation:** export effective history before inserting the new checkpoint,
  matching today's user-visible transcript.
- **Risk:** session-summary stale detection becomes misleading once raw count
  differs from effective count.
  **Mitigation:** keep list/summarization consumers on effective counts for this
  pass and defer a dedicated checkpoint-aware summary revision plan.

## Implementation Steps

1. Add a `chat_sessions` migration namespace and checkpoint table/index
   migration in `core/chat/schema.py` using `SQLiteMigration` and
   `apply_sqlite_migrations`.
2. Add checkpoint dataclass and serialization helpers in `core/chat/chat_store.py`.
3. Add raw/effective mode support to store read/count/recent methods.
4. Implement effective-history reconstruction from latest checkpoint.
5. Add checkpoint insertion and raw high-water helper.
6. Update `compact_chat_history(...)` to insert checkpoints instead of calling
   `replace_session_messages(...)`.
7. Confirm all default consumers use effective history through the updated store
   methods.
8. Extend `chat_history_compaction` scenario with the validation target above.
9. Update architecture/tool docs to describe the new current contract.
10. Run targeted smoke checks and request maintainer full validation.

## Deferred Session-Summary Work

This plan intentionally does not refactor session-summary stale detection or
summary snapshots.

Follow-up planning should cover:

- whether future summary freshness fields should include additional provenance
  beyond the current monotonic `history_revision`
- whether durable `session_summary_snapshots` are introduced separately from
  the current latest-summary projection

## Follow-Up Consumers

Most history consumers are already checkpoint-safe because `ChatStore` defaults
to effective replay history. The remaining follow-up consumers are:

- `retrieve_sessions(...)` stale summary logic. Handled with a monotonic
  `history_revision` stored in chat session metadata and copied into summary
  metadata at extraction/update time.
- `session_ops._list_sessions(...)` summary status. Handled with the same
  revision-aware `session_summary_status(...)` helper.
- `core/memory/session_summary.py` metadata contract. Current summaries can
  store `history_revision`; older summaries without that field still fall back
  to message-count comparison.
- `core/authoring/helpers/retrieve_sessions.py`. Handled with
  revision-aware pending/stale selection and returned revision metadata.
- Future archival/debug/export consumers. Raw transcript export, audit
  inspection, or deep raw search should explicitly request `mode="raw"` and
  clearly label the result as archival.

## Next Phase

Move to Feature Development after this plan is accepted. Start with the schema
and store API changes, then update compaction writes, then adjust validation and
docs.
