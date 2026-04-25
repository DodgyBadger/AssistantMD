# Chat Sessions Subsystem

Chat session state is persisted canonically in SQLite. Markdown transcripts are optional derived exports.

## Primary code

- `core/chat/chat_store.py` — read/write sessions and messages
- `core/chat/schema.py` — SQLite schema bootstrap
- `core/chat/transcript_writer.py` — export markdown transcripts from stored session data on demand

## SQLite store

`system/chat_sessions.db` is the canonical record. It has three tables:

- **`chat_sessions`** — one row per session: `session_id`, `vault_name`, `created_at`, `last_activity_at`, `title`
- **`chat_messages`** — full provider-native message objects stored as JSON, plus extracted `content_text`, `role`, `direction`, and `sequence_index` for querying
- **`chat_tool_events`** — structured tool call and result events keyed by `tool_call_id`, with `args_json`, `result_text`, and optional `artifact_ref`

## Markdown transcripts

`AssistantMD/Chat_Sessions/` contains optional markdown exports derived from the SQLite store rather than the primary record. `transcript_writer.py` renders them on demand by reading stored messages and formatting only user-visible user/assistant turns.

## History loading

`ChatStore.get_history()` returns the full `list[ModelMessage]` for a session, which the chat executor passes directly to the model as prior context. This replaces the old approach of re-parsing the markdown transcript.

Canonical history contains completed prior turns only while a chat run is in flight. The active user input is passed separately to Pydantic AI and is persisted only after completion through the provider-native `new_messages()` for that run. Do not pre-store the active prompt in `chat_messages`; doing so creates duplicate user turns and makes memory/context assembly ambiguous.
