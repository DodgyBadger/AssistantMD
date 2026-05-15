# Memory Subsystem

The memory subsystem is the shared broker for conversation-history access. It keeps tool adapters and authored scripts from each reinventing how session history is loaded and normalized.

## Primary code

- `core/memory/service.py` — broker, providers, normalized result types
- `core/memory/providers.py` — compatibility re-exports for older provider imports
- `core/authoring/helpers/history/retrieve.py` — Monty `retrieve_history(...)` adapter
- `core/authoring/helpers/history/assemble.py` — Monty `assemble_context(...)` adapter
- `core/tools/memory_ops.py` — LLM-facing memory tool adapter
- `core/chat/chat_store.py` — persisted SQLite-backed message source

## Responsibilities

- Resolve the best conversation-history source for the current run.
- Normalize provider-native messages into structured history records.
- Expose persisted chat tool events when available.
- Provide one host-owned service underneath both LLM tools and authoring helpers.

## Provider Model

`MemoryService` resolves one of two current providers:

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
field search. Conversation history is not exposed through `memory_ops`; if chat
history should become memory, it should first be exported or extracted into
vault artifacts or direct session memory fields. Context scripts should use
`retrieve_history(...)` and `assemble_context(...)` for context reassembly. If a
lower-level caller needs direct access to individual provider-native parts, it
should use a lower-level service/provider interface rather than the
general-purpose LLM tool.

## Design Notes

- The broker is intentionally flexible; policy belongs in callers such as the authoring helpers.
- Protocol safety for context assembly is enforced by returning tool exchanges as atomic units in `retrieve_history(...)`.
- Future memory primitives, including vector retrieval, should live behind this subsystem rather than directly in chat or tool modules.
