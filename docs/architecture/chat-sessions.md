# Chat Sessions Subsystem

Chat session state is persisted canonically in SQLite. Markdown transcripts are optional derived exports.

## Primary code

- `core/chat/chat_store.py` — read/write sessions and messages
- `core/chat/schema.py` — SQLite schema bootstrap
- `core/chat/transcript_writer.py` — export markdown transcripts from stored session data on demand
- `core/chat/history_service.py` — broker over persisted and in-memory conversation history
- `core/chat/compaction.py` — summarize long sessions and record replay checkpoints
- `core/chat/executor.py` — shared chat preparation, model/tool configuration, and history helpers
- `core/chat/task_execution.py` — task-owned chat execution, event buffering, and per-session queueing
- `core/chat/deferred_reviews.py` — durable deferred-tool review state and
  reviewed-target conflict detection

## SQLite store

`system/chat_sessions.db` is the canonical record. A `session_id` is globally unique and is permanently bound to the `vault_name` recorded on the session row. Chat execution resolves this binding before running the model; reusing an existing `session_id` with another vault returns `ChatSessionVaultMismatch`.

The main tables are:

- **`chat_sessions`** — one row per session: identity, vault binding, timestamps,
  title, and JSON metadata such as workspace and chat mode
- **`chat_messages`** — full provider-native message objects stored as JSON, plus extracted `content_text`, `role`, `direction`, and `sequence_index` for querying
- **`chat_tool_events`** — structured tool call and result events keyed by `tool_call_id`, with `args_json`, `result_text`, and optional `artifact_ref`
- **`chat_deferred_reviews`** — pending and terminal Pydantic AI deferred-tool
  requests, serialized continuation messages/configuration, review-time target
  state, submitted results, and resumed task identity
- **`chat_compaction_checkpoints`** — compaction replay checkpoints with a
  system-maintained replacement history and the raw-message sequence boundary
  covered by that checkpoint

Provider reasoning/thinking parts are transient by default. Chat persistence
removes `ThinkingPart` entries from assistant responses before writing durable
history so replay remains portable across providers and avoids recurring
reasoning-token overhead. The general setting
`persist_model_reasoning_parts=true` opts into storing those provider-native
parts. When reasoning parts are not persisted, provider response item IDs that
depend on an exact provider-native reasoning graph are also removed before
replay.

## Workspace metadata

Chat sessions may store a vault-relative workspace path in session metadata.
The workspace is a convenience hint for context assembly; it does not change
the session's vault binding, restrict file access, or change the vault root
used by tools. Saved workspace paths are allowed to become stale if a vault is
reorganized.

Session summaries denormalize the current workspace path into
`session_summaries.workspace_path` so future retrieval can filter prior work by
workspace without reparsing chat-session metadata.

## Session Mode

Each session stores a `chat_mode` metadata value:

- `normal` executes enabled chat tools normally.
- `inline_edit` routes `file_write` calls through inline deferred review.

`default_chat_mode` initializes new sessions only. Changing the mode through
`PATCH /api/chat/sessions/{session_id}/mode` persists that session's selection,
and session list/detail/fork contracts return it. Reloading an existing session
therefore restores its selected mode rather than consulting the current default.

## Deferred Tool Review

Inline review is a durable continuation boundary, not a browser-only artifact.
When Pydantic AI returns `DeferredToolRequests`, chat execution persists the
provider-native messages produced so far and stores the deferred requests,
resume messages, model/tool/context configuration, and review-time file state in
`chat_deferred_reviews`. The originating execution task then completes with
`finish_reason="tool_review_required"`.

Session detail returns the newest pending review so the UI can reconstruct the
card after reload. A session may have only one actionable pending continuation:
ordinary chat starts are rejected while it remains pending, and the web composer
is locked until the review is submitted. Terminal review cards are not rebuilt
on reload; approved and denied tool results become normal provider-native tool
history when the continuation runs.

Review submission is an atomic state transition from `pending` to `resuming`.
The backend validates decision call IDs, permitted argument overrides, and any
captured existing-file hashes before claiming the review. It then starts a new
chat task through the same per-session execution gate. The review reaches
`completed`, `failed`, or `cancelled` with that resumed task, preventing duplicate
submission from replaying a tool call.

## Markdown transcripts

`AssistantMD/Chat_Sessions/` contains optional markdown exports derived from the SQLite store rather than the primary record. `transcript_writer.py` renders them on demand by reading stored messages and formatting only user-visible user/assistant turns.

## History loading

`ChatStore.get_history()` returns the effective `list[ModelMessage]` for a session, which the chat executor passes directly to the model as prior context.

Canonical history contains completed prior turns plus the accepted user request for an active chat run. The active user input is passed separately to Pydantic AI, and provider-native response messages are persisted after completion through `new_messages()` for that run. On cancellation, the accepted user request remains persisted and no assistant response is added.

For uncompacted sessions, effective history is the stored raw message sequence.
For compacted sessions, effective history is reconstructed from the latest
compaction checkpoint plus raw messages appended after that checkpoint. Raw
pre-checkpoint messages remain in `chat_messages` for durability, but normal
runtime readers use effective history by default. Replay sends the effective
history through the current reasoning history policy: persisted reasoning is
kept when enabled or already present as complete provider-native history, while
partial provider item graphs are normalized to portable transcript replay.

`core/chat/history_service.py` is the shared broker over this store for tools,
session summarization, and authoring helpers. Context scripts should access
session history through `retrieve_history(...)`, which preserves tool
call/return pairs as atomic units before `assemble_context(...)` hands curated
history back to chat.

## Execution tasks and cancellation

Chat execution registers a process-local task scoped to `chat_session:<session_id>`.

- Chat turns use the same task kind (`chat`) and API source (`api`).
- Chat starts with `POST /api/chat/tasks` and streams
  buffered events from `GET /api/chat/tasks/{task_id}/events`.
- Task-owned streaming is the canonical chat execution path. Callers that do
  not need live tokens still submit a chat task and can observe task state or
  reload persisted session history after completion.
- Chat event streaming emits SSE keepalive comments from the subscriber loop during
  idle waits so long-running model or tool calls keep the response connection
  active without tying the model run to that subscriber.
- If a subscriber disconnects, the chat task continues running unless cancelled.
- Multiple chat starts for the same session are serialized by
  creation time. Later tasks stay `queued` until older non-terminal chat tasks
  in the same session finish, so each run prepares against completed prior
  history.
- A deferred-review continuation is also a chat task in that same queue. It
  resumes with stored messages and `DeferredToolResults` without persisting a
  second user request.
- `chat_tool_calls_limit` applies Pydantic AI `UsageLimits(tool_calls_limit=...)` to chat runs when the setting is positive; `0` disables this guard.
- `delegate_tool_calls_limit` and `delegate_timeout_seconds` separately bound child agents launched by `delegate(...)`.
- `/api/chat/sessions/{session_id}/active-task` returns the active chat task for a session.
- `/api/chat/sessions/{session_id}/cancel` requests cancellation for the active chat task.
- `/api/tasks/{task_id}/cancel` cancels a known chat task id directly.
- A cancelled chat task reaches terminal status `cancelled`; the session remains queryable through normal session detail endpoints.

See [Execution Tasks](execution-tasks.md) for task lifecycle and cancellation semantics.

## Session ownership

Every durable chat session has one immutable `owner_principal_id`. Interactive
requests currently resolve to the built-in `local-user` principal, and existing
session rows are assigned to that principal by the chat database migration.
Session touches never rewrite ownership, and forks retain the source session's
owner. Ownership is an internal authorization contract and is not exposed in
the current chat-session API models.

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
