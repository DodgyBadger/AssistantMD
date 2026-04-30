# Memory Subsystem

The memory subsystem is the shared broker for conversation-history access. It keeps tool adapters and authored scripts from each reinventing how session history is loaded and normalized.

## Primary code

- `core/memory/service.py` — broker, providers, normalized result types
- `core/memory/providers.py` — compatibility re-exports for older provider imports
- `core/authoring/helpers/history/retrieve.py` — Monty `retrieve_history(...)` adapter
- `core/authoring/helpers/history/assemble.py` — Monty `assemble_context(...)` adapter
- `core/tools/memory_ops.py` — optional LLM-facing memory tool adapter
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

Both providers return `ConversationHistoryResult` and `ConversationToolEventResult` objects with normalized item records.

## Authoring Contract

Context scripts should use `retrieve_history(...)` rather than reading chat storage directly. The helper returns safe history units:

- one user message
- one assistant message
- one atomic tool call + tool return exchange

`assemble_context(...)` accepts those safe units and preserves provider-native message fidelity for downstream chat context. The latest active message is not appended by scripts; the chat runtime adds it once after assembled history.

## Tool Contract

`memory_ops` is the optional LLM-facing adapter over the same service when enabled in settings. Its purpose is inspection and retrieval for an agent, not context reassembly. If a lower-level caller needs direct access to individual provider-native parts, it should use a lower-level service/provider interface rather than the general-purpose LLM tool.

## Design Notes

- The broker is intentionally flexible; policy belongs in callers such as the authoring helpers.
- Protocol safety for context assembly is enforced by returning tool exchanges as atomic units in `retrieve_history(...)`.
- Future memory primitives, including vector retrieval, should live behind this subsystem rather than directly in chat or tool modules.
