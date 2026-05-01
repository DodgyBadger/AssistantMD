# Chat History Compaction Spec

## Goal

Add user-guided chat history compaction that rewrites canonical stored chat history into a shorter summary plus recent turns.

This is different from context assembly. Context assembly changes what gets injected into one prompt. History compaction changes the durable session history loaded by `ChatStore` for future turns.

## User Contract

When a session grows large, AssistantMD should advise the user inside the conversation:

- the chat history is large enough that compaction is recommended soon
- compaction rewrites canonical chat history into a summary plus recent turns
- if the user wants the full verbatim conversation, they should export the transcript before compacting
- the user can approve, decline, or provide focus instructions

The agent must not compact until the user explicitly agrees.

Examples of valid user replies:

- "yes"
- "yes, focus on architecture decisions and unresolved tasks"
- "not now"
- "compact but keep the current debugging thread detailed"

## Product Shape

Start with a hybrid model:

- Manual compaction is always available through a tool/API.
- Advisory mode nudges the user when history crosses a threshold.
- Automatic compaction can be added later as a policy layer, but should not be the first default.

Initial recommended default:

- `chat_history_compaction_mode: suggest`
- no automatic rewrite without user approval

Future modes:

- `manual`: user must invoke compaction explicitly
- `suggest`: inject advisory and let the conversation decide
- `auto_after_turn`: compact after an assistant response completes, never during a response
- `force_before_turn`: rare hard-limit mode when the next prompt is likely unsafe

## Existing Architecture

Relevant current modules:

- `core/chat/executor.py`: prepares chat execution, persists accepted user messages before model execution, persists response-side messages after completion
- `core/chat/chat_store.py`: canonical SQLite-backed chat session history
- `core/runtime/execution_tasks.py`: generic process-local task tracking
- `api/endpoints.py` and `api/services.py`: chat session APIs, task APIs, transcript export
- `core/tools/`: chat tools exposed through the normal `BaseTool` interface
- `static/app.js`: chat UI and session export control

Transcript export already exists:

- `POST /api/chat/sessions/{session_id}/export`
- `exportCurrentSession()` in `static/app.js`

## Design

### 1. Store-Level Rewrite Primitive

Add a transactional rewrite operation to `ChatStore`:

```python
replace_session_messages(
    session_id: str,
    vault_name: str,
    messages: list[ModelMessage],
) -> None
```

Requirements:

- preserve `chat_sessions` row, title, and metadata
- delete old `chat_messages` rows for the session
- insert replacement messages with fresh sequence indexes
- update `last_activity_at`
- run in one SQLite transaction
- do not delete transcript exports

This is the canonical destructive operation. Higher-level services should call this, not manipulate chat tables directly.

### 2. Compaction Service

Add `core/chat/compaction.py`.

Responsibilities:

- estimate current session history size
- decide whether advisory threshold is crossed
- build a compaction prompt from older messages and optional user focus instructions
- call a configured model to create the summary
- build replacement history:
  - one system-maintained summary message
  - the most recent raw turns, unchanged
- call `ChatStore.replace_session_messages(...)`
- return a structured result

The summary message should be clearly system-maintained history, not a fake user message. Prefer a `ModelRequest` containing a `SystemPromptPart` if Pydantic AI accepts it as stable stored history. Verify this before implementation.

Suggested result fields:

- `session_id`
- `vault_name`
- `status`
- `messages_before`
- `messages_after`
- `estimated_tokens_before`
- `estimated_tokens_after`
- `kept_recent_turns`
- `summary_message_index`
- `export_recommended`

### 3. Execution Task Integration

Run compaction as an execution task:

- `kind="history_compaction"`
- `scope="chat_session:<session_id>"`
- `source="api" | "tool" | "system"`
- label like `compact:<session_id>`

Use `runtime.task_coordinator.track_current_task(...)` so compaction has status, cancellation, and activity-log visibility.

Concurrency rule:

- compaction must not rewrite history while an active chat task for the same session is running
- first implementation can reject with a clear error if another active task exists in that scope
- later implementation can queue after the chat task completes

### 4. Advisory Injection

Add advisory detection in chat preflight after canonical history is loaded and before the agent call.

If threshold is crossed and advisory is not on cooldown, inject an instruction into the current prompt context telling the agent to recommend compaction.

The advisory should instruct the agent to:

- tell the user compaction is recommended
- explain that canonical history will be rewritten
- recommend exporting the transcript first if the user wants the full verbatim text
- ask whether to compact now
- invite focus instructions
- avoid compacting without explicit approval

The advisory should not appear every turn. Add cooldown/session metadata such as:

- `last_compaction_advisory_at`
- `last_compaction_advisory_token_estimate`
- `compaction_declined_at`

Store this in chat session metadata if practical; otherwise use a small side table or metadata JSON update helper in `ChatStore`.

### 5. Compaction Tool

Add a chat-visible tool, likely `chat_history_compact`.

Tool inputs:

- `operation`: `status`, `compact`
- `focus`: optional user instructions for what the summary should preserve
- `export_first`: optional boolean; default false

Tool behavior:

- `status`: report current estimate and whether compaction is recommended
- `compact`: run the compaction task after explicit user approval
- if `export_first=true`, export the transcript before rewriting history
- if `export_first=false`, remind that export was recommended but not performed

The tool should only operate on the active vault/session from chat context. It should not accept arbitrary filesystem paths.

Tool response should be compact and agent-readable:

```text
success: True
operation: compact
session_id: ...
status: completed
messages_before: ...
messages_after: ...
exported_transcript: ...
summary_focus: ...
```

### 6. API Surface

Add service and endpoints for non-agent/manual UI use:

- `GET /api/chat/sessions/{session_id}/compaction-status?vault_name=...`
- `POST /api/chat/sessions/{session_id}/compact`

Request model:

- `vault_name`
- `focus`
- `export_first`

Response model:

- task snapshot or completed compaction result

Initial implementation can be synchronous from the API while still tracked by `TaskCoordinator`; async/polling can follow if compaction is slow.

### 7. UI Surface

Keep UI minimal at first:

- show a compact badge or note when compaction is recommended
- provide a "Compact history" button near existing session export controls
- keep the existing "Export" button visible
- if user clicks compact, show a modal/confirm text explaining:
  - canonical history will be rewritten
  - export first if they want a verbatim transcript
  - optional focus instructions

The conversational advisory remains the primary flow. UI is an escape hatch and status surface.

## Settings

Add settings to `core/settings/settings.template.yaml`:

- `chat_history_compaction_mode`: `suggest`
- `chat_history_compaction_threshold_tokens`: initial conservative value, e.g. `80000`
- `chat_history_compaction_hard_threshold_tokens`: initial higher value, e.g. `120000`
- `chat_history_compaction_keep_recent_turns`: e.g. `8`
- `chat_history_compaction_advisory_cooldown_turns`: e.g. `3`
- `chat_history_compaction_model`: optional model alias, default empty meaning use selected/default model

Add accessors in `core/settings/__init__.py`.

## Safety Rules

- Never compact during an active chat response.
- Never compact without explicit approval in `manual` or `suggest` mode.
- Always recommend transcript export before destructive rewrite.
- Preserve recent turns verbatim.
- Preserve enough metadata to make it clear a session was compacted.
- Do not delete exported transcripts.
- Do not summarize secrets or API keys more explicitly than they appeared in the conversation.

## Validation Targets

Add focused scenarios:

1. `chat_history_compaction_status`
   - create a session with enough stored messages to cross threshold
   - assert status reports compaction recommended

2. `chat_history_compaction_manual`
   - compact a session with focus instructions
   - assert canonical history is rewritten to summary plus recent turns
   - assert recent turns remain verbatim
   - assert no transcript export is deleted

3. `chat_history_compaction_export_first`
   - compact with `export_first=true`
   - assert transcript export exists before rewrite
   - assert response includes exported filename/path

4. `chat_history_compaction_advisory`
   - run chat after threshold is crossed
   - assert the agent receives an advisory instruction
   - assert no compaction happens without tool/API approval

5. `chat_history_compaction_concurrency`
   - start a long chat task
   - attempt compaction for the same session
   - assert compaction is rejected or deferred without rewriting history

## Open Decisions

- Exact compacted summary message type: `SystemPromptPart` vs another Pydantic AI message shape.
- Whether compaction should create an automatic transcript export by default.
- Whether compaction should be synchronous in the first API/tool version or immediately use async task polling.
- Whether the advisory is injected by `core/chat/executor.py` directly or by the default context assembly script. The likely answer is executor-level because the trigger depends on canonical `ChatStore` size and cooldown metadata.
- How to count tokens for multimodal/image-heavy messages. Initial implementation can count text only and include image references in the summary prompt.

## Phased Implementation

### Phase 0: Store Rewrite And Estimation

- Add `ChatStore.replace_session_messages(...)`.
- Add history estimation helpers.
- Add tests/scenario coverage for transactional rewrite.

### Phase 1: Manual Compaction Service

- Add `core/chat/compaction.py`.
- Implement summary generation and replacement history construction.
- Add API endpoint for compact now.
- Track compaction with `TaskCoordinator`.

### Phase 2: Tool Contract

- Add `core/tools/chat_history_compact.py`.
- Add tool metadata/settings entry.
- Add docs under `docs/tools/`.
- Validate approval/focus-instruction flow.

### Phase 3: Advisory Injection

- Add threshold/cooldown settings.
- Inject advisory into chat preflight when needed.
- Persist advisory cooldown metadata.
- Validate that advisory appears without triggering compaction.

### Phase 4: UI Controls

- Add compaction status indicator.
- Add compact button and focus-instruction confirmation.
- Reuse existing transcript export path.

### Phase 5: Optional Automation

- Add `auto_after_turn` mode only after manual/suggest flows are validated.
- Ensure compaction never interrupts an active chat task.
