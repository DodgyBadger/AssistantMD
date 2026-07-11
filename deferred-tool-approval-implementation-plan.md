# Inline Editing Implementation Plan

## Goal

Make writing and editing markdown files feel native inside AssistantMD's chat
workflow. The user should be able to collaborate with the agent on concrete file
changes without repeatedly switching to Obsidian or another editor for routine
draft/review/save loops.

The desired loop is:

1. The agent proposes concrete file changes.
2. The user inspects those changes inline.
3. The user approves, tweaks, rejects, or comments at the point of change.
4. Approved changes write immediately through normal vault mutation paths.
5. If the edit was part of a broader task, the agent continues naturally.
6. Chat history remains understandable to future agents and summarizers.

Pydantic AI deferred tool approvals are the implementation mechanism for the
pause/resume parts of this loop. They are not the product goal, and this effort
should not be framed primarily as a security or permission system.

## Decision

Adopt Pydantic AI's deferred approval protocol for interactive inline
file review:

- file-changing chat tools can use `requires_approval=True` or raise
  `ApprovalRequired` when the active review policy calls for inline review;
- chat execution accepts `DeferredToolRequests` as an agent output;
- review submissions return `DeferredToolResults` with `ToolApproved`,
  `ToolApproved(override_args=...)`, or `ToolDenied(message=...)`;
- the chat runner resumes from the prior message history so the agent can
  continue the task after reviewed writes complete.

AssistantMD still owns:

- when chat file writes become inline review cards;
- how review requests are persisted and rendered;
- the inline edit/review card UI;
- vault path policy, conflict checks, and mutation routing;
- task lifecycle events and reload behavior.

This keeps the mechanism aligned with the agent framework while preserving the
AssistantMD product experience.

## Current State

- `propose_file_edits` creates a server-owned artifact and returns an
  `artifact_ref`.
- The browser renders that artifact as an edit proposal card.
- Approved rows are applied through FastAPI endpoints and shared vault mutation
  helpers.
- Mixed comment/deny reviews are converted into a new user prompt that starts a
  follow-up chat task.
- Apply-only approval does not resume the original agent run, so multi-step
  agentic work stalls until the user manually prompts again.
- Apply-only approval history is currently represented by synthetic user and
  assistant messages so summarization can see what happened.

That behavior is useful for explicit draft review, but it is not a true paused
tool call. It therefore falls short when the agent is mid-task and needs to
continue after the user accepts the changes.

## Non-Goals

- Do not create a custom assistant-authored markup language for review UI.
- Do not let frontend code author model prompts or review semantics.
- Do not bypass `core.vault_state.file_operations` or
  `core.vault_state.file_mutations` for approved writes.
- Do not require inline review in workflows, context assembly scripts,
  scheduled jobs, or other unattended automation.
- Do not solve every file operation shape in the first slice.

## Product Framing

This is an inline editor and writing workflow, not a sandbox. The
blast radius of AssistantMD file changes is limited by the vault boundary,
snapshots, mutation audit, and rollback support. Some operations are more
disruptive than others, especially delete, truncate, move, and broad edits, but
the primary reason to show a card is not fear of damage. It is to make
back-and-forth writing smoother and more inspectable.

Use "review" language in product-facing code and UI where possible:

- `inline_review`;
- `review card`;
- `review request`;
- `review policy`;
- `submitted review`.

Use "approval" language only where it maps directly to Pydantic AI's API or
internal protocol terms:

- `requires_approval`;
- `DeferredToolRequests`;
- `DeferredToolResults`;
- `ToolApproved`;
- `ToolDenied`.

## Review Policy

The policy layer decides when an interactive chat file write becomes an inline
review card. It should not be modeled primarily as a risk/permission matrix.

User-facing modes:

- `normal`: let the agent write directly when the user intent is clear.
- `inline_edit`: show inline review UI for agent-proposed file changes.

The default for new chats comes from `default_chat_mode` and is `normal` in the
settings template.

Operation categories still matter, but mainly for UI and workflow shape:

- `create_file`: content-focused review, usually lightweight.
- `replace_text` / `edit`: replacement or diff review.
- `move_file`: destination/path review.
- `delete_file`: explicit rejection/confirm affordance.
- `batch`: grouped review card for related changes.

The policy decision should combine:

- execution surface;
- operation category;
- user review mode;
- tool-specific context, such as whether the operation is a batch.

Return decisions:

- `allow_direct`;
- `defer_for_inline_review`;
- `block_with_message`.

## Automation Boundary

Workflows and context assembly scripts can call configured tools through Monty
direct-tool wrappers. Those runs must never wait for inline review because there
is no active reviewer.

Required invariant:

- deferred review is available only in interactive chat execution;
- automation execution contexts must either use non-deferred tool adapters or
  fail fast before a deferred request is created.

Concrete policy:

- Add an execution-mode signal to tool binding or run deps, for example
  `execution_surface="chat" | "automation" | "delegate"`.
- Mutating vault operations may be deferred for inline review only when
  `execution_surface == "chat"` and an interactive review sink is available.
- Direct Monty tool calls in `core/authoring/runtime/monty_runner.py` must not
  expose wrappers that can pause for review.
- If a review-only operation is accidentally invoked from automation, return a
  structured failure such as `inline_review_unavailable` rather than waiting.
- Existing workflow behavior should be preserved initially. Workflow safety and
  audit continue to come from explicit workflow code, tool-specific
  confirmations, task mutation audit, rollback support, and scheduler/task
  governance.

Open question:

- Should automation eventually declare explicit write/delete capabilities per
  workflow? That is a separate automation-governance question. The first
  implementation should preserve current automation behavior unless there is a
  clear product reason to tighten it.

## Target Architecture

### 1. Review-Aware Tool Binding

Introduce a small policy layer that can produce different tool wrappers for
different execution surfaces.

Initial surfaces:

- `interactive_chat`: may expose deferred review wrappers;
- `automation`: never exposes deferred review wrappers;
- `delegate`: initially treat like non-interactive unless the parent chat run
  explicitly supports nested review, which should be deferred to a later
  design.

This should live near existing tool binding/capability code rather than inside
individual FastAPI endpoints.

Candidate files:

- `core/authoring/shared/tool_binding.py`
- `core/llm/capabilities/assistant_tools.py`
- `core/chat/executor.py`
- `core/authoring/runtime/monty_runner.py`

### 2. Deferred File Operation Adapter

Create a chat-facing mutating file operation adapter that uses the existing
vault operation service for validation and execution.

The adapter should not duplicate file operation logic. It should translate
between:

- Pydantic tool args and review metadata;
- approved override args and prepared vault operations;
- core service rejection codes and model-visible tool results.

First operation set:

- replace text;
- create file;
- delete file;
- move file.

The existing `propose_file_edits` artifact tool can remain available while the
new review path is built, but it should no longer be the default mechanism for
agentic mid-task file writes once deferred review is working.

### 3. Chat Runner Pause And Resume

Extend task-owned chat execution to recognize deferred review output.

When the agent returns `DeferredToolRequests`:

- persist the model messages needed to resume;
- persist a durable review request record scoped to vault/session/task;
- emit a chat task event such as `review_required`;
- mark the chat task as waiting for review or terminal-with-waiting metadata,
  depending on the least invasive task lifecycle change;
- render the review card from the persisted request.

When the user submits a review:

- build `DeferredToolResults`;
- include per-call decisions and `override_args` for user-edited content/path
  values;
- resume the same logical chat run using prior message history;
- stream resumed output through the same chat task event path;
- persist final Pydantic messages once the resumed run completes.

Primary files:

- `core/chat/task_execution.py`
- `core/chat/executor.py`
- `core/chat/task_events.py`
- `core/chat/chat_store.py`
- `api/endpoints.py`
- `api/services.py`

### 4. Review Persistence

Add a durable review request store. It can be a new table or an evolution of
the existing edit proposal artifact table if that remains clean.

Store:

- review id / artifact ref;
- vault name;
- session id;
- originating task id;
- tool call id;
- tool name;
- validated args;
- review metadata;
- status: pending, approved, denied, resumed, expired, failed;
- created/updated timestamps;
- resulting resumed task id if a new task record is used.

Persist application data, not pre-rendered HTML.

### 5. UI Contract

Reuse the existing edit proposal card renderer where possible.

For deferred file operations, card rows map to tool review calls:

- approve maps to `ToolApproved`;
- approve after editing replacement/content/path maps to
  `ToolApproved(override_args=...)`;
- deny with optional reason maps to `ToolDenied(message=...)`;
- comment is a product-level affordance that likely maps to deny-with-message
  for the current tool call, followed by agent continuation.

After submission:

- lock the card;
- collapse historical cards;
- show pending/applied/denied/resumed status;
- do not allow a stale historical card to submit another review.

### 6. Chat History And Summarization

The resumed run should leave canonical Pydantic message history containing the
tool call and review outcome. Nightly summarization and future agents should not
need to infer review state from browser-only artifacts.

Until this is proven in local inspection, keep a fallback plan for adding a
small synthetic history note only when Pydantic's persisted messages do not make
the review outcome understandable.

## Phased Implementation

### Phase 1: Spike The Protocol

- Build a narrow test-only or hidden chat tool with `requires_approval=True`.
- Confirm how `run_stream_events` surfaces `DeferredToolRequests`.
- Confirm exactly which messages must be persisted before resume.
- Confirm `ToolApproved(override_args=...)` executes with edited args.
- Confirm denied calls are visible to the model as tool results.
- Document findings in this plan before changing production file tools.

Phase 1 findings from `validation/scenarios/experiments/deferred_tool_review_probe.py`:

- A tool marked `requires_approval=True` returns `DeferredToolRequests` as the
  run output when `output_type=[str, DeferredToolRequests]`.
- The deferred tool does not execute before review.
- `DeferredToolRequests.approvals` contains the original `ToolCallPart`,
  including `tool_name`, validated args, and stable `tool_call_id`.
- Resuming uses the `deferred_tool_results=` run parameter with the previous
  `message_history`; the `DeferredToolResults` object is not passed as a new
  user prompt.
- `ToolApproved(override_args=...)` executes the original tool with edited args
  and appends a canonical `ToolReturnPart` for the original `tool_call_id`.
- `ToolDenied(message=...)` does not execute the tool, but still resumes the run
  and appends a canonical tool return containing the denial reason.
- `run_stream_events(...)` emits a `FunctionToolCallEvent` for the deferred tool
  call and then an `AgentRunResultEvent` whose output is
  `DeferredToolRequests`.

Implementation implication: the production chat runner needs to detect
`AgentRunResultEvent.result.output` as `DeferredToolRequests`, persist
`result.all_messages()` for resume, and later call `run_stream_events(...)` or
`run(...)` with `deferred_tool_results=` and that persisted message history.

### Phase 2: Task And API Skeleton

- Add review request persistence.
- Add review-required chat task event serialization.
- Add endpoints to fetch and submit pending reviews.
- Add task metadata/status support for waiting review without breaking the
  existing queued chat serialization contract.
- Add targeted tests for pending review persistence and stale submission
  rejection.

Phase 2 initial slice:

- Added durable `chat_deferred_reviews` storage for pending inline review
  requests, including serialized `DeferredToolRequests` and resume
  `ModelMessage` history.
- Pending review records now persist their own resume config: model, tools,
  thinking label, context template, and workspace path.
- Chat agents now allow `DeferredToolRequests` as output alongside normal text.
- Task-owned streaming chat detects deferred review output, persists the pending
  review, emits `review_required`, and closes the current stream with
  `finish_reason: "tool_review_required"`.
- Added a read endpoint for pending review artifacts:
  `GET /api/vaults/{vault_name}/chat/{session_id}/deferred-reviews/{artifact_ref}`.
- Added a submit endpoint for review decisions:
  `POST /api/vaults/{vault_name}/chat/{session_id}/deferred-reviews/{artifact_ref}/submit`.
- Submit maps approved calls to `ToolApproved` or
  `ToolApproved(override_args=...)`, denied calls to `ToolDenied`, starts a
  linked resume task with stored resume config plus `deferred_tool_results=...`,
  and marks the review submitted with `resumed_task_id`.
- Auto-compaction is skipped for a turn that pauses for inline review so a
  dangling tool call is not compacted before it receives a review result.
- Added `validation/scenarios/integration/core/deferred_review_task_skeleton.py`
  to prove the production task path creates a pending review record, exposes it
  through the API, submits edited override args, starts a resume task, and
  rejects stale repeat submissions.

Remaining Phase 2 work:

- Add reload-oriented validation once the frontend renders deferred review cards.

### Phase 3: File Operation Review Adapter

- Wrap replace/create/delete/move file operations with deferred review for
  interactive chat.
- Route approved executions through `core.vault_state.file_operations`.
- Preserve current direct behavior for automation.
- Return structured tool results matching existing file operation metadata.

Phase 3 initial slice:

- Added `review_create_file`, a narrow reviewed create-file tool that accepts
  `path` and `content`, uses Pydantic `requires_approval=True`, and writes only
  after the deferred review is approved.
- Approved execution routes through
  `core.vault_state.file_operations.prepare_create_file` and
  `write_prepared_create_file`, preserving normal vault mutation behavior.
- Approved override args can change the destination path or content before
  execution.
- Denied calls do not write.
- Registered the tool in settings for explicit chat use, but did not add it to
  default chat tools yet.
- Excluded `review_create_file` from Monty direct-tool exposure because it is an
  interactive review affordance and automation has no active reviewer.
- Added `validation/scenarios/integration/core/review_create_file_tool.py` to
  prove real Pydantic deferred execution creates a vault file only after review.

### Phase 4: UI Integration

- Render deferred file reviews with the existing card structure.
- Support approve, deny, comment/reason, and edited override args.
- Lock and collapse submitted cards.
- Handle reloads and stale review state.

Phase 4 initial slice:

- Added a browser-side deferred review controller in
  `static/js/deferred-reviews.js`.
- Task stream `review_required` events now render inline as message artifacts,
  not in the tool-call section.
- Deferred review cards reuse the existing edit proposal card visual language:
  collapsible header, pending/submitted status, approve all, deny all, per-row
  approve/deny actions, editable content fields, and optional denial reasons.
- The submit button stays disabled until every pending call has an approve or
  deny decision, matching the backend requirement that review submissions cover
  all deferred tool calls.
- Approved `review_create_file` calls submit edited `content` and `path` values
  as `override_args`.
- Submitted cards lock immediately and collapse. The follow-up resume task then
  streams through the normal chat task event path.

Remaining Phase 4 work:

- Add reload-oriented validation proving persisted pending/submitted review
  cards render correctly after a session reload.
- Add browser/manual validation for mobile layout and long proposed content.
- Extend the renderer beyond `review_create_file` as replace/delete/move review
  adapters are introduced.

### Phase 5: Migration And Cleanup

- Decide whether `propose_file_edits` remains as a final-review artifact tool,
  becomes a compatibility shim, or is retired.
- Remove duplicate prompt-building paths when deferred review covers the same
  behavior.
- Update tool docs and regular chat instructions to prefer the real mutating
  tool with inline review rather than `propose_file_edits` for mid-task writes.

## Validation Targets

Targeted local checks:

- unit/service coverage for review request persistence;
- integration scenario for a deferred test tool approve/resume path;
- integration scenario for approved file replacement continuing the agent turn;
- integration scenario for denied/commented file operation returning a visible
  denial result to the model;
- regression scenario proving Monty workflow/context direct tool calls do not
  create pending reviews or wait for user input.

Manual/browser checks:

- review card appears inline in chat;
- edited replacement content is submitted as override args;
- approving all resumes the agent without a manual "proceed";
- historical submitted cards lock and collapse;
- mobile layout remains usable.

Maintainers still own full validation runs.

## Next Concrete Step

Start with Phase 1. Build the smallest deferred-review spike around a hidden
tool or isolated test route, then inspect the exact Pydantic messages and stream
events before changing production file operation tools.
