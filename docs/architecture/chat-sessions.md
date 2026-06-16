# Chat Sessions Subsystem

Chat session state is persisted canonically in SQLite. Markdown transcripts are optional derived exports.

## Primary code

- `core/chat/chat_store.py` — read/write sessions and messages
- `core/chat/schema.py` — SQLite schema bootstrap
- `core/chat/transcript_writer.py` — export markdown transcripts from stored session data on demand
- `core/chat/history_service.py` — broker over persisted and in-memory conversation history
- `core/chat/compaction.py` — summarize long sessions and record replay checkpoints
- `core/chat/executor.py` — register chat execution tasks and persist completed turns

## SQLite store

`system/chat_sessions.db` is the canonical record. A `session_id` is globally unique and is permanently bound to the `vault_name` recorded on the session row. Chat execution resolves this binding before running the model; reusing an existing `session_id` with another vault returns `ChatSessionVaultMismatch`.

The main tables are:

- **`chat_sessions`** — one row per session: `session_id`, `vault_name`, `created_at`, `last_activity_at`, `title`
- **`chat_messages`** — full provider-native message objects stored as JSON, plus extracted `content_text`, `role`, `direction`, and `sequence_index` for querying
- **`chat_tool_events`** — structured tool call and result events keyed by `tool_call_id`, with `args_json`, `result_text`, and optional `artifact_ref`
- **`chat_compaction_checkpoints`** — compaction replay checkpoints with a
  system-maintained replacement history and the raw-message sequence boundary
  covered by that checkpoint

## Workspace metadata

Chat sessions may store a vault-relative workspace path in session metadata.
The workspace is a convenience hint for context assembly; it does not change
the session's vault binding, restrict file access, or change the vault root
used by tools. Saved workspace paths are allowed to become stale if a vault is
reorganized.

Session summaries denormalize the current workspace path into
`session_summaries.workspace_path` so future retrieval can filter prior work by
workspace without reparsing chat-session metadata.

## Markdown transcripts

`AssistantMD/Chat_Sessions/` contains optional markdown exports derived from the SQLite store rather than the primary record. `transcript_writer.py` renders them on demand by reading stored messages and formatting only user-visible user/assistant turns.

## History loading

`ChatStore.get_history()` returns the effective `list[ModelMessage]` for a session, which the chat executor passes directly to the model as prior context.

Canonical history contains completed prior turns plus the accepted user request for an active chat run. The active user input is passed separately to Pydantic AI, and provider-native response messages are persisted after completion through `new_messages()` for that run. On cancellation, the accepted user request remains persisted and no assistant response is added.

For uncompacted sessions, effective history is the stored raw message sequence.
For compacted sessions, effective history is reconstructed from the latest
compaction checkpoint plus raw messages appended after that checkpoint. Raw
pre-checkpoint messages remain in `chat_messages` for durability, but normal
runtime readers use effective history by default.

`core/chat/history_service.py` is the shared broker over this store for tools,
session summarization, and authoring helpers. Context scripts should access
session history through `retrieve_history(...)`, which preserves tool
call/return pairs as atomic units before `assemble_context(...)` hands curated
history back to chat.

## Execution tasks and cancellation

Chat execution registers a process-local task scoped to `chat_session:<session_id>`.

- Non-streaming and streaming chat runs both use the same task kind (`chat`) and API source (`api`).
- `chat_tool_calls_limit` applies Pydantic AI `UsageLimits(tool_calls_limit=...)` to chat runs when the setting is positive; `0` disables this guard.
- `delegate_tool_calls_limit` and `delegate_timeout_seconds` separately bound child agents launched by `delegate(...)`.
- `/api/chat/sessions/{session_id}/active-task` returns the active chat task for a session.
- `/api/chat/sessions/{session_id}/cancel` requests cancellation for the active chat task.
- A cancelled chat task reaches terminal status `cancelled`; the session remains queryable through normal session detail endpoints.

See [Execution Tasks](execution-tasks.md) for task lifecycle and cancellation semantics.

## History compaction

Chat history compaction records a replay checkpoint whose default effective
history starts with:

1. A system-maintained summary message marked with `AssistantMD compacted chat history`.
2. A recent raw message slice preserved verbatim.

The compaction split preserves tool call/return pairs in the recent slice.
Compaction does not create transcript exports; users can export chat transcripts
manually from the UI when needed.

Compaction leaves existing `chat_messages` rows intact, records the raw-message
high-water mark covered by the checkpoint, and writes audit metadata under the
session's `last_compaction` metadata key, including compaction ID, timestamp,
source, before/after effective message counts, token estimates, and checkpoint
boundary.

Default session detail, transcript export, `retrieve_history(...)`,
`assemble_context(...)`, and model-context assembly use effective history, not
archival raw history.

Compaction can be invoked by:

- API: `/api/chat/sessions/{session_id}/compact`
- chat tool: `chat_history_compact`
- automatic post-turn compaction when configured with `compaction_type: auto` and the estimated token threshold is reached; `auto` is the default for new settings files

Compaction emits stable lifecycle events: `chat_compaction_started`, `chat_compaction_plan_selected`, `chat_compaction_completed`, and `chat_compaction_failed`.
