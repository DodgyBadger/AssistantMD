# Memory Subsystem

The memory subsystem stores and retrieves derived session memory. Chat history
brokering lives in the chat subsystem so memory records remain distinct from the
conversation history they are derived from.

## Primary code

- `core/memory/session_memory.py` — session-memory storage, indexing, and retrieval
- `core/memory/schema.py` — SQLite schema bootstrap for `system/memory.db`
- `core/chat/history_service.py` — chat-history broker, providers, normalized result types
- `core/authoring/helpers/history/retrieve.py` — Monty `retrieve_history(...)` adapter
- `core/authoring/helpers/retrieve_sessions.py` — Monty `retrieve_sessions(...)` adapter
- `core/authoring/helpers/history/assemble.py` — Monty `assemble_context(...)` adapter
- `core/tools/memory_ops.py` — LLM-facing memory tool adapter
- `core/chat/chat_store.py` — persisted SQLite-backed message source

## Responsibilities

- Store extracted memory fields for chat sessions.
- Index memory fields for lexical and vector retrieval.
- Attach output artifacts discovered from chat-scoped vault mutations.
- Expose session-memory creation, update, lookup, and search through `memory_ops`.
- Use the chat-history broker when memory extraction needs source conversation history.

## Provider Model

`ChatHistoryService` in `core/chat/history_service.py` resolves one of two
current providers:

- `SQLiteConversationHistoryProvider`: used when the requested session has persisted messages in `system/chat_sessions.db`.
- `InMemoryConversationHistoryProvider`: used for active in-flight history when persisted history is not yet available.

Persisted session history is the default source when a requested session has stored messages.
Callers may explicitly opt into in-memory history for the active session when they have already
curated the message list.

Both providers return `ConversationHistoryResult` and `ConversationToolEventResult` objects with normalized item records.

## Authoring Contract

Context scripts should use `retrieve_history(...)` rather than reading chat storage directly. The helper returns safe history units:

- one user message
- one assistant message
- one atomic tool call + tool return exchange

`assemble_context(...)` accepts those safe units and preserves provider-native message fidelity for downstream chat context. The latest active message is not appended by scripts; the chat runtime adds it once after assembled history.

Workflow scripts can use `retrieve_sessions(selection="pending_memory")` to enumerate
current-vault chat sessions that do not yet have a derived session-memory row.
The helper returns session metadata only; it does not retrieve transcript
messages or perform extraction. Workflows should compose it with `memory_ops`
when they need to extract memory for selected sessions.

During active context assembly, the context manager passes curated prior history in
`message_history` and exposes the current user prompt through `latest_message`. That path
explicitly opts into the in-memory history source so `retrieve_history(...)` cannot see the active
prompt that has already been accepted into the durable chat store for cancellation safety. Outside
context assembly, authored history retrieval defaults to persisted session history when it exists,
including after process restart.

## Tool Contract

`memory_ops` is the LLM-facing adapter for session memory operations. It is
available through the normal configured tool path, so chat agents and authored
scripts use the same operation surface for session memory lookup, updates, and
search. Conversation history is not exposed through `memory_ops`; if chat
history should become memory, it should first be exported or extracted into
vault artifacts or direct session memory fields. `extract_session_memory` uses
the shared chat-history broker to read conversation history before deriving session
memory fields. Context scripts should use `retrieve_history(...)` and
`assemble_context(...)` for context reassembly. If a
lower-level caller needs direct access to individual provider-native parts, it
should use a lower-level service/provider interface rather than the
general-purpose LLM tool.

Session retrieval is exposed as `search_sessions` with modes rather than direct
field selection. `related` compares the current or specified session against
stored memory; `search` fans a user query across memory fields using FTS/BM25
and vector evidence; `deep` adds FTS/BM25 over raw chat transcripts. Field-aware
storage and scoring remain internal implementation details.

## Design Notes

- The chat-history broker is intentionally flexible; policy belongs in callers such as the authoring helpers.
- Protocol safety for context assembly is enforced by returning tool exchanges as atomic units in `retrieve_history(...)`.
- Future derived-memory primitives, including vector retrieval, should live behind this subsystem rather than directly in chat or tool modules.
