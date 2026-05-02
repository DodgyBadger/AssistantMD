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

- Manual compaction is always available through the API and the chat-visible tool.
- Suggested compaction nudges the user when history crosses a threshold.
- Automatic compaction uses the same underlying service, but runs as a policy layer rather than a tool call.

Initial recommended default:

- `compaction_type: suggested`
- no automatic rewrite without user approval

Supported modes:

- `none`: no advisory and no automatic compaction; manual API/tool compaction remains available
- `suggested`: expose a UI/API recommendation and let the user decide
- `auto`: compact after an assistant response completes when the threshold is crossed, never during a response

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
- update compaction metadata in the same transaction
- run in one SQLite transaction
- do not delete transcript exports

This is the canonical destructive operation. Higher-level services should call this, not manipulate chat tables directly.

### 2. Compaction Service

Add `core/chat/compaction.py`.

This service is the underlying implementation for every compaction pathway. The chat tool, API endpoint, UI flow, suggested advisory flow, and automatic policy should all call this service instead of each owning compaction logic. Automatic compaction must not go through a chat-visible tool call.

Responsibilities:

- estimate current session history size
- decide whether advisory threshold is crossed
- build a compaction prompt from older messages, the base compaction instruction, and optional user focus instructions
- call a configured model to create the summary
- build replacement history:
  - one system-maintained summary message
  - the most recent raw turns, unchanged
- call `ChatStore.replace_session_messages(...)`
- return a structured result

The base compaction instruction should live in `core/constants.py`, not in the tool implementation. This keeps the summary contract stable across tool, API, UI, suggested, and automatic entry points.

The summary message should be clearly system-maintained history, not a fake user message. Prefer a `ModelRequest` containing a `SystemPromptPart` if Pydantic AI accepts it as stable stored history. Verify this before implementation.

When selecting recent raw history, `compaction_keep_recent` is a target, not permission to split message pairs. If the slice boundary would separate a tool call from its matching tool result, shift the boundary backward so the whole pair remains in the preserved recent history.

Repeated compactions should recognize prior compaction summaries and merge or replace them cleanly. The rewritten history should not accumulate nested summaries that get progressively harder for the agent to interpret.

Suggested service API shape:

```python
compact_chat_history(
    session_id: str,
    vault_name: str,
    *,
    focus: str | None = None,
    export_before: bool | None = None,
    source: Literal["api", "tool", "system"] = "api",
) -> ChatHistoryCompactionResult
```

Suggested result fields:

- `session_id`
- `vault_name`
- `status`
- `messages_before`
- `messages_after`
- `estimated_tokens_before`
- `estimated_tokens_after`
- `kept_recent`
- `summary_message_index`
- `export_recommended`
- `export_created`
- `export_path`, for API/UI callers only
- `compaction_id`
- `compacted_at`
- `source`

### 3. Execution Task Integration

Run compaction as an execution task:

- `kind="history_compaction"`
- `scope="chat_session:<session_id>"`
- `source="api" | "tool" | "system"`
- label like `compact:<session_id>`

Use `runtime.task_coordinator.track_current_task(...)` so compaction has status, cancellation, and activity-log visibility.

Concurrency rule:

- compaction must have exclusive write access to the chat session history while it rewrites canonical messages
- if compaction is running for a session, a new chat turn for that same session should pause or queue until compaction completes
- if a chat turn is already actively streaming or persisting response messages, compaction should wait until that response reaches a stable persistence boundary, then run before the next chat turn proceeds
- the task layer should make this coordination visible as task status rather than allowing concurrent history mutation

### 4. UI Recommendation Detection

Expose recommendation detection through status APIs after canonical history is loaded and estimated.

If `compaction_type` is `suggested`, the threshold is crossed, and recommendation display is not on cooldown, the UI should surface a compact non-chat notice.

The UI recommendation should:

- tell the user compaction is recommended
- explain that canonical history will be rewritten
- recommend exporting the transcript first if the user wants the full verbatim text
- offer compact now, not now, and optional focus instructions
- avoid triggering compaction without explicit approval

The recommendation should not appear every turn. Add cooldown/session metadata such as:

- `last_compaction_advisory_at`
- `last_compaction_advisory_token_estimate`
- `compaction_declined_at`

Store this in chat session metadata if practical; otherwise use a small side table or metadata JSON update helper in `ChatStore`.

If `compaction_type` is `auto`, the policy should run after an assistant response has completed and persisted, using the compaction service directly. It should not inject a tool call and should not compact while the current response is still streaming or being saved.

### 5. Compaction Tool

Add a chat-visible tool, likely `chat_history_compact`.

The tool is a thin authorization and presentation layer over `core/chat/compaction.py`. It should not contain the summary prompt, slicing rules, export behavior, or rewrite logic.

Tool inputs:

- `operation`: `status`, `compact`
- `focus`: optional user instructions for what the summary should preserve
- `export_before`: optional boolean; default from `compaction_export_before`

Tool behavior:

- `status`: report current estimate and whether compaction is recommended
- `compact`: run the compaction task after explicit user approval
- if `export_before=true`, export the transcript before rewriting history
- if `export_before=false`, remind that export was recommended but not performed

The tool should only operate on the active vault/session from chat context. It should not accept arbitrary filesystem paths.

Tool response should be compact and agent-readable. It must not include the exported transcript path or filename. Returning the path to the chat agent risks the agent reading the transcript and undermining compaction.

```text
success: True
operation: compact
session_id: ...
status: completed
messages_before: ...
messages_after: ...
export_created: True
summary_focus: ...
```

### 6. API Surface

Add service and endpoints for non-agent/manual UI use:

- `GET /api/chat/sessions/{session_id}/compaction-status?vault_name=...`
- `POST /api/chat/sessions/{session_id}/compact`

Request model:

- `vault_name`
- `focus`
- `export_before`

Response model:

- task snapshot or completed compaction result

API/UI responses may include an exported transcript path for user-facing display. Chat-visible tool responses must not.

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

Automatic compaction should leave a visible activity/status record outside the chat transcript so the user can see that history was rewritten. It should not inject a synthetic assistant message solely to announce background compaction.

## Settings

Add settings to `core/settings/settings.template.yaml`:

- `compaction_type`: `none | auto | suggested`, default `suggested`
- `compaction_keep_recent`: integer target for recent raw turns/messages to keep, e.g. `8`
- `compaction_token_threshold`: integer threshold for suggested or automatic compaction, e.g. `80000`
- `compaction_export_before`: boolean default for transcript export before rewrite, default `false`

Add accessors in `core/settings/__init__.py`.

Advisory cooldown should exist, but it can start as an internal/session metadata policy rather than a user-facing setting. A model override can be added later if the default configured model proves unsuitable for compaction.

## Safety Rules

- Never mutate canonical history concurrently with chat persistence for the same session.
- Pause or queue new chat turns while compaction owns the session history.
- Never compact without explicit approval in `none` or `suggested` mode.
- Always recommend transcript export before destructive rewrite.
- Preserve recent turns verbatim.
- Do not split tool call/tool result pairs when preserving recent turns.
- Preserve enough metadata to make it clear a session was compacted.
- Do not delete exported transcripts.
- Do not return exported transcript paths or filenames to the chat agent.
- Do not summarize secrets or API keys more explicitly than they appeared in the conversation.
- Generate the summary before rewriting history, and only perform the rewrite after summary generation succeeds.
- Treat the rewrite and metadata update as one transaction.
- Avoid repeatedly nesting prior compaction summaries.

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
   - assert compaction metadata is recorded

3. `chat_history_compaction_export_first`
   - compact with `export_before=true`
   - assert transcript export exists before rewrite
   - assert API/UI response includes exported filename/path when appropriate
   - assert chat-visible tool response does not include exported filename/path

4. `chat_history_compaction_advisory`
   - run chat after threshold is crossed
   - assert status/API reports a recommendation for UI display
   - assert no compaction happens without tool/API approval

5. `chat_history_compaction_concurrency`
   - start a long chat task
   - start compaction for the same session
   - assert chat and compaction do not concurrently mutate canonical history
   - assert the waiting task resumes after the session history reaches a stable state

6. `chat_history_compaction_tool_pairs`
   - create history where the recent boundary would split a tool call/result pair
   - assert the preserved recent slice shifts backward and keeps the pair intact

7. `chat_history_compaction_repeated`
   - compact a session that already contains a compaction summary
   - assert the new history does not accumulate nested summary clutter

## Open Decisions

- Exact compacted summary message type: `SystemPromptPart` vs another Pydantic AI message shape.
- Whether API/UI should offer a one-click export-and-compact flow even when `compaction_export_before=false`.
- Whether compaction should be synchronous in the first API/tool version or immediately use async task polling.
- Exact UI placement and cooldown behavior for suggested compaction notices.
- How to count tokens for multimodal/image-heavy messages. Initial implementation can count text only and include image references in the summary prompt.
- Whether automatic compaction should record a UI notification/activity item so users can see that history was rewritten outside the chat transcript.
- Whether repeated compaction should merge prior summaries into a new summary or preserve the latest prior summary as structured source material.

## Phased Implementation

### Phase 0: Store Rewrite And Estimation

- Add `ChatStore.replace_session_messages(...)`.
- Add history estimation helpers.
- Add compaction audit metadata fields/helpers.
- Add tests/scenario coverage for transactional rewrite.

### Phase 1: Manual Compaction Service

- Add `core/chat/compaction.py`.
- Add base compaction instruction to `core/constants.py`.
- Implement summary generation and replacement history construction.
- Implement recent-history slicing that preserves tool call/result pairs.
- Implement prior-summary handling for repeated compactions.
- Add API endpoint for compact now.
- Track compaction with `TaskCoordinator`.

### Phase 2: Tool Contract

- Add `core/tools/chat_history_compact.py`.
- Add tool metadata/settings entry.
- Add docs under `docs/tools/`.
- Validate approval/focus-instruction flow.

### Phase 3: UI Recommendation Detection

- Add compaction settings and advisory cooldown metadata.
- Expose recommendation status for UI display when needed.
- Persist advisory cooldown metadata.
- Validate that recommendation status appears without triggering compaction.

### Phase 4: Automatic Policy

- Add `compaction_type=auto` handling after assistant responses complete.
- Route automatic compaction through the service, not through a tool call.
- Record enough metadata/activity for user visibility.
- Validate that automatic compaction coordinates with active chat execution without concurrent history mutation.

### Phase 5: UI Controls

- Add compaction status indicator.
- Add compact button and focus-instruction confirmation.
- Reuse existing transcript export path.
