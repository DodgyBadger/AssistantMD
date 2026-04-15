# Chat Session SQLite Store Plan

## Goal

Replace the current in-memory chat session history with a durable SQLite-backed store that:

- preserves structured provider-native chat/run messages as the canonical source of truth
- preserves tool calls, tool returns, and cached artifact references in a replayable form
- keeps markdown transcripts as a secondary user-facing artifact
- supports future DB-first memory retrieval and vector-enhanced memory work

This is a persistence and runtime-contract change, not just a refactor. The design should stay simple, explicit, and easy to inspect.

## Follow-On Design Topics

These do not need to be fully decided in the first implementation slice, but the design must leave room for them:

- UI integration
  - resume old chats
  - purge old chats
  - revise how tool calls and tool results are presented in the message window
- non-chat run persistence
  - context-template runs
  - workflow runs

The first implementation should not hardcode assumptions that make those later steps awkward or impossible.

## Current Problems

- The core SQLite rollout is now in place; remaining work is mostly UI/lifecycle and read-model refinement.
- Context-template and follow-up chat paths needed hardening so processed history preserves the active turn correctly.

## Design Principles

- Use `core/database.py` as the system-database entry point. Do not add ad hoc path handling.
- Give chat sessions their own SQLite file. Do not overload `cache.db`.
- Keep the canonical store structured and replayable.
- Keep transcript rendering downstream of the structured store.
- Prefer a small number of clearly named modules over generic wrappers.
- Reuse existing code where it already has the right responsibility; refactor only where separation is currently muddy.

## Proposed Database

Add a new declared system database in [database.py](/app/core/database.py):

- `chat_sessions`

Reason:

- the data is durable runtime state
- it is logically separate from:
  - `cache`
  - `file_state`
  - scheduler state
- it will likely grow its own lifecycle, migration, and indexing concerns

Expected file:

- `system/chat_sessions.db`

## Canonical Data Model

Use the SQLite store as the canonical chat-session event log.

### 1. `chat_sessions`

One row per session.

Suggested fields:

- `session_id`
- `vault_name`
- `created_at`
- `last_activity_at`
- `title` nullable
- `metadata_json`

Future-proofing note:

- the schema should leave room for a future `session_type` or equivalent discriminator
- first implementation can remain chat-only without exposing that field yet

### 2. `chat_messages`

One row per persisted provider-native `ModelMessage`.

Suggested fields:

- `id`
- `session_id`
- `vault_name`
- `sequence_index`
- `direction`
  - `request`
  - `response`
- `message_type`
  - provider-native class name
- `role`
  - normalized convenience field
- `content_text`
  - normalized text projection for search/debug
- `message_json`
  - canonical serialized message payload
- `created_at`

Notes:

- `message_json` is the source of truth
- `content_text` is an indexed projection, not the canonical record
- `sequence_index` must be stable and gap-free within a session

### 3. `chat_tool_events`

One row per tool call/result event that we want to preserve as structured memory.

Suggested fields:

- `id`
- `session_id`
- `vault_name`
- `message_id` nullable
- `tool_call_id`
- `tool_name`
- `event_type`
  - `call`
  - `result`
  - `overflow_cached`
- `args_json`
- `result_text`
- `result_metadata_json`
- `artifact_ref` nullable
- `created_at`

Notes:

- this avoids forcing all tool semantics through flattened message text
- it lets us preserve cache refs and structured tool metadata for future reuse
- this table is not a replacement for provider-native messages; it is a parallel structured index for important tool events

## Recommended Scope Split

### Phase 1: Session Store Only

Implement durable structured session history in `chat_sessions.db`.

Includes:

- persisted sessions
- persisted provider-native messages
- persisted tool-event metadata sufficient for memory/reuse decisions

Does not require:

- moving chat overflow artifacts out of `cache.db` yet

### Phase 2: Artifact Unification

Revisit whether oversized tool-result artifacts should:

- stay in `cache.db` with better indexing/lookup from session data
- or move into `chat_sessions.db`

Recommendation:

- do not force artifact unification into Phase 1
- keep the first slice smaller and easier to validate
- keep artifact bodies in `cache.db` for now
- store artifact refs in `chat_tool_events` instead of duplicating artifact bodies in the session store

### Phase 3: UI Integration

Follow-on work after the core store is stable:

- list resumable chat sessions in the UI
- reopen prior sessions cleanly
- purge/delete sessions and associated derived transcript artifacts according to policy
- revisit message-window rendering for tool calls, tool returns, and cached-artifact references

Recommendation:

- do not bake UI formatting concerns into the canonical DB schema
- store the structured facts and let the UI choose how to render them

## Module Layout

Use a dedicated package with straightforward names.

Recommended structure:

- [chat_store.py](/app/core/chat/chat_store.py)
  - high-level session/message persistence API used by chat executor
- [schema.py](/app/core/chat/schema.py)
  - table creation and migration helpers
- [transcript_writer.py](/app/core/chat/transcript_writer.py)
  - markdown transcript rendering/writing from structured session data

If the package does not already exist, create:

- `core/chat/`

Avoid:

- generic “manager” wrappers that only forward calls
- mixing transcript rendering with DB writes in one file
- putting chat-session persistence into `core/context/store.py`

Future-proofing note:

- if context/workflow runs later use the same persistence substrate, extend the same package with clearly named modules
- do not generalize the first implementation so far that the chat path becomes harder to understand

## Database Layer Reuse

Reuse [database.py](/app/core/database.py) directly:

- add `chat_sessions` to `SYSTEM_DATABASES`
- use `get_system_database_path(...)`
- use `connect_sqlite_from_system_db(...)`

Refactor where needed:

- if `core/context/store.py` has helpers worth sharing, extract those helpers into a neutral sqlite utility only if more than one DB truly needs them
- do not move chat-session concepts into `core/context/store.py`

## SessionManager Direction

Current [session_manager.py](/app/core/llm/session_manager.py) is in-memory only.

Recommended path:

- convert `SessionManager` into a thin, real persistence service backed by `chat_store`
- keep its public surface only if it is still the clearest integration point for chat executor
- otherwise rename it to match the new responsibility

Recommendation:

- keep the name only if it still owns session-history operations after the refactor
- if it becomes just a delegating shim, remove it and let chat executor call `chat_store` directly

## Transcript Strategy

Markdown transcripts remain secondary artifacts.

Open question to defer until after the DB store exists:

- write per turn
- write after inactivity
- write after N turns
- write on demand

Recommendation for first implementation:

- keep current transcript behavior as close as possible to reduce variables
- render transcript entries from the canonical structured store, not from ad hoc prompt/response strings

## Completed

- Added `chat_sessions` to the declared system databases and ensured SQLite connections honor the active runtime `system_root`.
- Added `core/chat/` with:
  - `chat_store.py`
  - `schema.py`
  - `transcript_writer.py`
  - package exports in `__init__.py`
- Implemented durable `chat_sessions`, `chat_messages`, and `chat_tool_events` persistence in `chat_sessions.db`.
- Switched `SessionManager` to the SQLite-backed store.
- Persisted canonical provider-native `ModelMessage` payloads in `chat_messages.message_json`.
- Persisted structured tool events in `chat_tool_events` for `call`, `result`, and `overflow_cached`.
- Rewrote markdown chat transcripts from persisted canonical session data.
- Updated `memory_ops` to keep the existing provider boundary while reading from the SQLite store.
- Refactored `memory_ops(get_history)` to be the primary retrieval surface over canonical ordered chat messages.
- Added retrieval-time `message_filter` controls:
  - `all`
  - `exclude_tools`
  - `only_tools`
- Kept `get_tool_events` as a secondary diagnostic/index view rather than a replay requirement.
- Added targeted persistence validation in [chat_session_persistence_contract.py](/app/validation/scenarios/integration/core/chat_session_persistence_contract.py).
- Extended overflow validation in [chat_tool_overflow_cache.py](/app/validation/scenarios/integration/core/chat_tool_overflow_cache.py) so cached oversized tool results remain covered after the persistence rollout.
- Fixed context-manager history processing so:
  - only real user prompts anchor “latest user” detection
  - the active turn suffix is preserved during history processing
  - authoring-style context templates reattach the active turn correctly on follow-up requests
- Reproduced the `Processed history must end with a ModelRequest` bug against the live FastAPI endpoint and verified the fix with a real two-turn same-session chat.
- Added minimal chat-session browse APIs for the UI:
  - vault-scoped session listing ordered by `last_activity_at`
  - session-detail loading for message-area rehydration
- Added a compact chat-session dropdown to the chat settings UI scoped to the selected vault.
- Implemented session selection so choosing a persisted session rehydrates the visible chat history, not just `session_id`.
- Updated session rehydration to suppress raw persisted tool-call/tool-return text bubbles and rebuild tool activity into the assistant bubble’s collapsible tool-calls section.

## Validation Completed

- `python validation/run_validation.py run integration/core/authoring_context_assembly integration/core/chat_session_persistence_contract integration/core/chat_tool_overflow_cache`
- Live FastAPI repro:
  - first `POST /api/chat/execute` on a fresh session succeeded
  - second `POST /api/chat/execute` on the same session also succeeded after the context-manager fix

## Remaining Work

- UI/session lifecycle work:
  - ~~delete/purge sessions and associated derived transcript artifacts~~ — done
- session UI refinement:
  - improve session labels beyond raw session ids
  - add richer session metadata when useful
- Decide whether `chat_tool_events` needs explicit linkage back to canonical messages for future merged UI/debug timelines.
- Update user-facing/tooling docs for the current `memory_ops` contract, including `message_filter` and the diagnostic `get_tool_events` path.

That means:

- transcript writes are still frequent initially
- but transcript content is now derived from persisted session data

## MemoryOps Implications

`memory_ops` should move from in-memory history to the SQLite-backed session store.

Phase-1 behavior:

- `memory_ops(get_history, scope="session")` reads from `chat_sessions.db`
- it treats persisted provider-native messages as the canonical source of truth
- it exposes retrieval-time shaping/filtering over that canonical history instead of creating a second canonical representation

Important:

- do not regress to transcript parsing
- keep `message_json` as the canonical replay surface
- keep tool-event metadata auxiliary so replay/resume never depends on `chat_tool_events`
- keep the provider boundary open enough that later chat, context, or workflow histories could be served through the same tool contract

## Tool Result Preservation

This design should explicitly preserve tool reuse signals.

Minimum first-pass requirement:

- persist tool name
- persist tool call id
- persist normalized args JSON
- persist normalized result metadata JSON
- persist cache/artifact ref when present

This is necessary so follow-up prompts can reason over:

- “I already extracted this URL”
- “that tool result overflowed and lives at this ref”
- “this doc was already read”

without relying only on flattened assistant text.

UI note:

- these structured tool-event records should support richer future message rendering without forcing the canonical session history itself to become UI-shaped

## Validation Targets

### Scenario Updates

- extend or add a scenario for durable chat restart behavior:
  - create a session
  - persist messages and tool activity
  - rehydrate session history from SQLite
  - verify `memory_ops` returns the same structured history after restart

- extend chat follow-up reuse scenarios:
  - tool result recorded in session store
  - follow-up turn can see the prior tool metadata / artifact ref

- extend current Monty/context-template scenarios only as needed:
  - verify the current user turn remains visible in `memory_ops`
  - verify history order remains stable

### Smoke Tests

- targeted local smoke test for DB init and session write/read round-trip
- targeted local smoke test for transcript rendering from persisted messages
- targeted local smoke test for tool-event persistence with an overflow cache ref

## Affected Areas

- [database.py](/app/core/database.py)
- [chat_executor.py](/app/core/llm/chat_executor.py)
- [session_manager.py](/app/core/llm/session_manager.py)
- [memory_ops.py](/app/core/tools/memory_ops.py)
- new `core/chat/` package
- transcript writing helpers currently embedded in chat executor

Potentially:

- [store.py](/app/core/context/store.py), only if we deliberately extract shared sqlite/cache helpers

Later, possibly:

- context/workflow execution modules if we decide those runs should also persist into the same session substrate

## Risks

- over-designing the schema before the first practical migration lands
- mixing canonical message storage with transcript rendering concerns
- storing only flattened text again and recreating the current weakness in a DB
- introducing a thin wrapper layer that adds indirection without clarity
- moving artifact storage and session storage at the same time and making validation harder
- prematurely generalizing chat sessions into an abstract all-runs store before the chat case is solid

## Recommended Implementation Order

1. Add `chat_sessions` to [database.py](/app/core/database.py).
2. Create `core/chat/schema.py` and `core/chat/chat_store.py`.
3. Persist provider-native session messages to SQLite while keeping current transcript writes.
4. Refactor `SessionManager` to read/write through the store or remove it if it becomes redundant.
5. Switch `memory_ops` from in-memory provider to SQLite-backed provider.
6. Add structured tool-event persistence for tool calls/results and overflow refs.
7. Rework transcript writing to render from structured session data instead of raw prompt/response inputs.
8. Revisit artifact unification with `cache.db` only after the above is stable.
9. Design and implement UI session management against the stabilized store.

## Current Rollout Status

Completed:

- [x] Declared `chat_sessions` in [database.py](/app/core/database.py).
- [x] Added `core/chat/` with:
  - [chat_store.py](/app/core/chat/chat_store.py)
  - [schema.py](/app/core/chat/schema.py)
  - [transcript_writer.py](/app/core/chat/transcript_writer.py)
- [x] Moved [session_manager.py](/app/core/llm/session_manager.py) onto the SQLite-backed store for session history reads/writes.
- [x] Persist provider-native `ModelMessage` history into `chat_sessions.db`.
- [x] Persist structured tool events for `call`, `result`, and `overflow_cached` paths from chat execution.
- [x] Switched transcript writing to rewrite markdown from persisted session data after successful chat turns.
- [x] Switched `memory_ops(get_history, scope="session")` to prefer persisted SQLite chat history and fall back to in-memory history only when no persisted session exists.
- [x] Refactored `memory_ops(get_history)` so it reads from canonical ordered message history, includes provider-native message payloads inline, and supports retrieval-time filtering (`all`, `exclude_tools`, `only_tools`).
- [x] Kept `chat_tool_events` as an auxiliary structured index rather than a replay dependency.
- [x] Fixed raw sqlite runtime-root handling so validation/runtime isolation uses the active `system_root`.
- [x] Added deterministic persistence-contract coverage proving a real chat turn persists provider-native messages, structured tool events, transcripts, and restart-time `memory_ops` retrieval:
  [chat_session_persistence_contract.py](/app/validation/scenarios/integration/core/chat_session_persistence_contract.py)
- [x] Ran targeted local checks:
  - validation scenario `integration/core/authoring_context_assembly`
  - validation scenario `integration/core/chat_session_persistence_contract`
  - validation scenario `integration/core/chat_tool_overflow_cache`
  - transcript rewrite smoke test against a temporary runtime root

Still open:

- [ ] transcript-format refinements for tool-heavy or multimodal sessions
- [ ] dedicated read APIs/helpers for stored tool-event inspection and future UI rendering
- [ ] decide whether `chat_tool_events` needs a stronger ordering/linkage key for future merged UI/debug views, even though replay no longer depends on it
- [x] Boundary cleanup: removed `SessionManager` shim, moved `chat_executor.py` → `core/chat/executor.py`, deleted dead `chat_defaults.py`
- [x] UI session browsing, resume, and delete flows
- [ ] retention/cleanup policy for old sessions and derived transcript artifacts
- [ ] follow-up validation for retrieval-time history filtering (`exclude_tools`, `only_tools`) in additional Monty/chat workflows

## Follow-On Cleanup

Completed: boundary cleanup pass is done.

- `session_manager.py` removed; `chat_executor.py` moved to `core/chat/executor.py`
- `core/llm` now contains only genuinely LLM-centric concerns: `agents.py`, `model_selection.py`, `model_utils.py`

## Deferred Design Questions

- Should context-template runs and workflow runs eventually persist into the same store?
- If yes, are they first-class sessions or related run records under a broader session umbrella?
- Should cache artifacts remain globally reusable by ref, or should some later artifact classes become session-owned records?
- What is the retention/deletion policy for old sessions and their transcript artifacts?
- At what cadence should markdown transcripts be written once the DB is canonical?
- How should tool calls, tool returns, and cached-artifact refs be rendered in the chat UI once structured records are available?

## Next Phase

Feature Development
