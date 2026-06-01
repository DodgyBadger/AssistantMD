# Session Summary Subsystem

AssistantMD uses "memory" as a broad composition pattern: users can combine
tools, skills, workflows, context scripts, and vault files to preserve useful
context over time. The concrete subsystem described here stores and retrieves
derived session summaries.

Session summaries are indexes over prior chat sessions. They are one memory
primitive, not the whole memory model. Chat history brokering lives in the chat
subsystem so derived summary records remain distinct from the conversation
history they are derived from.

## Primary code

- `core/memory/session_summary.py` — session-summary storage, indexing, and retrieval
- `core/memory/schema.py` — SQLite schema bootstrap for `system/session_summaries.db`
- `core/chat/history_service.py` — chat-history broker, providers, normalized result types
- `core/authoring/helpers/history/retrieve.py` — Monty `retrieve_history(...)` adapter
- `core/authoring/helpers/retrieve_sessions.py` — Monty `retrieve_sessions(...)` adapter
- `core/authoring/helpers/history/assemble.py` — Monty `assemble_context(...)` adapter
- `core/tools/session_ops.py` — LLM-facing session lookup and summarization adapter
- `core/chat/chat_store.py` — persisted SQLite-backed message source

## Responsibilities

- Store derived summary fields for chat sessions.
- Index retrieval-oriented summary fields for lexical and vector retrieval.
- Store source provenance separately from indexed retrieval fields so source
  details can ground returned summaries without dominating candidate selection.
- Attach output artifacts discovered from chat-scoped vault mutations.
- Expose session-summary creation, update, lookup, and search through `session_ops`.
- Use the chat-history broker when session summarization needs source conversation history.

## Provider Model

`ChatHistoryService` in `core/chat/history_service.py` resolves one of two
current providers:

- `SQLiteConversationHistoryProvider`: used when the requested session has persisted messages in `system/chat_sessions.db`; compacted sessions return effective replay history by default.
- `InMemoryConversationHistoryProvider`: used for active in-flight history when persisted history is not yet available.

Persisted effective session history is the default source when a requested session has stored messages.
Callers may explicitly opt into in-memory history for the active session when they have already
curated the message list.

Both providers return `ConversationHistoryResult` and `ConversationToolEventResult` objects with normalized item records.

## Authoring Contract

Context scripts should use `retrieve_history(...)` rather than reading chat storage directly. The helper returns safe history units:

- one user message
- one assistant message
- one atomic tool call + tool return exchange

`assemble_context(...)` accepts those safe units and preserves provider-native message fidelity for downstream chat context. The latest active message is not appended by scripts; the chat runtime adds it once after assembled history.

Workflow scripts can use `retrieve_sessions(selection="pending_or_stale_summary")`
to enumerate current-vault chat sessions that either lack a stored summary or
have a stale summary. The helper returns session metadata only; it does not
retrieve transcript messages or perform summarization. Workflows should compose
it with `session_ops` when they need to summarize selected sessions. Stale
summary selection compares the current persisted session history revision with
the revision recorded when the summary was extracted. Raw message appends and
compaction checkpoints both advance that revision, so summary freshness does
not depend on message-count changes.

During active context assembly, the context manager passes curated prior history in
`message_history` and exposes the current user prompt through `latest_message`. That path
explicitly opts into the in-memory history source so `retrieve_history(...)` cannot see the active
prompt that has already been accepted into the durable chat store for cancellation safety. Outside
context assembly, authored history retrieval defaults to persisted session history when it exists,
including after process restart.

## Tool Contract

`session_ops` is the LLM-facing adapter for prior-session lookup and
summarization. It is available through the normal configured tool path, so chat
agents and authored scripts use the same operation surface for session-summary
lookup, updates, and search. Conversation history is not exposed through
`session_ops`; if chat history should become a summary, use
`summarize_session` or write explicit summary fields through
`upsert_session_summary`. `summarize_session` uses the shared chat-history
broker to read conversation history before deriving session-summary fields.
Context scripts should use `retrieve_history(...)` and `assemble_context(...)`
for context reassembly. If a lower-level caller needs direct access to
individual provider-native parts, it should use a lower-level service/provider
interface rather than the general-purpose LLM tool.

Session retrieval is exposed as `search_sessions` with modes rather than direct
field selection. `search` fans a user query across summary fields using FTS/BM25
and vector evidence; `deep` adds FTS/BM25 over the same effective chat history
used by normal session readers. Field-aware storage and scoring remain internal
implementation details.

## Design Notes

- The chat-history broker is intentionally flexible; policy belongs in callers such as the authoring helpers.
- Protocol safety for context assembly is enforced by returning tool exchanges as atomic units in `retrieve_history(...)`.
- Future derived session-summary retrieval behavior should remain behind this
  subsystem rather than being duplicated directly in chat or tool modules.
- Other memory primitives may exist alongside session summaries; they should be
  documented as separate contracts when they become concrete.
