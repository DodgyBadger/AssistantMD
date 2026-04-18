# Chat Sessions Subsystem

Chat session state is persisted in two places: a SQLite store (canonical) and a markdown transcript (derived, human-readable).

## Primary code

- `core/chat/chat_store.py` — read/write sessions and messages
- `core/chat/schema.py` — SQLite schema bootstrap
- `core/chat/transcript_writer.py` — render markdown transcripts from stored session data

## SQLite store

`system/chat_sessions.db` is the canonical record. It has three tables:

- **`chat_sessions`** — one row per session: `session_id`, `vault_name`, `created_at`, `last_activity_at`, `title`
- **`chat_messages`** — full provider-native message objects stored as JSON, plus extracted `content_text`, `role`, `direction`, and `sequence_index` for querying
- **`chat_tool_events`** — structured tool call and result events keyed by `tool_call_id`, with `args_json`, `result_text`, and optional `artifact_ref`

## Markdown transcripts

`AssistantMD/Chat_Sessions/` still contains one markdown file per session, but these are now derived from the SQLite store rather than being the primary record. `transcript_writer.py` renders them by reading stored messages and formatting each turn. The user prompt is also appended immediately on receipt (before the LLM responds) so abrupt failures still leave a readable trail.

## History loading

`ChatStore.get_history()` returns the full `list[ModelMessage]` for a session, which the chat executor passes directly to the model as prior context. This replaces the old approach of re-parsing the markdown transcript.
