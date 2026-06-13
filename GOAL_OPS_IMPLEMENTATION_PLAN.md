# Goal Ops Implementation Plan

## Purpose

Add a small `goal_ops` persistence primitive for longer knowledge-work tasks. The tool should let an agent durably record a goal, ordered steps, audit events, and compact checkpoints while leaving actual work execution to existing chat, workflow, file, and vault systems.

This is not a new autonomous mode, scheduler, planner, or artifact pipeline. It is a coordination primitive the default composition can use when a task is too large to keep only in chat history.

## Design Principles

- Markdown remains the user-facing work surface. Workspace files such as `goal.md`, `README.md`, or `playbook.md` are default composition choices, not mandatory authority.
- Goals belong to a vault. Any workspace path is only a hint for default composition and filtering, not a first-class workspace owner or required scope.
- SQLite is the runtime source of truth for exact ids, status, step ordering, event ordering, and checkpoints.
- `goal_ops` records state; it does not decide what work to do next.
- File creation and mutation remain owned by existing vault/file pathways.
- Related files are derived from existing task file mutation activity, using goal context on the execution task or mutation rows. `goal_ops` should not create a separate artifact table or write files directly.
- Tool execution should not be automatically retried by `goal_ops`. Tool failures should remain model-visible decision inputs.

## Initial Data Shape

### Goals

Fields:

- `goal_id`
- `vault_name`
- `workspace_path_hint`
- `source_type`: nullable system-inferred origin, initially `chat`, `workflow`, or `context`
- `source_id`: nullable stable source id such as chat session id, workflow global id, or context global id
- `source_task_id`: nullable execution task id for the run that created the goal, when available
- `source_label`: nullable display/debug label for the inferred source
- `title`
- `objective`
- `status`: `active`, `paused`, `completed`, `cancelled`, `blocked`
- `success_criteria_json`
- `metadata_json`
- `created_at`
- `updated_at`

Open question for implementation: whether `blocked` should be terminal or resumable. Default assumption: resumable.

### Steps

Exactly one explicit layer under a goal:

```text
Goal
  Step
```

No nested substeps in the initial data model. Deeper human-readable structure belongs in the step summary or workspace markdown.

Fields:

- `step_id`
- `goal_id`
- `position`
- `title`
- `status`: `pending`, `in_progress`, `completed`, `skipped`, `blocked`, `superseded`
- `summary`
- `metadata_json`
- `created_at`
- `updated_at`

Ordering must use `position`, not id or title. If a batch operation does not provide positions, assign sparse positions from array order: `10`, `20`, `30`, etc. List steps by `position ASC, created_at ASC`.

### Events

Events are goal-level audit entries. They should be useful for transparency and future summarization, not noisy traces of every internal operation.

Fields:

- `event_id`
- `goal_id`
- `step_id` nullable
- `event_type`: examples `created`, `plan_changed`, `status_changed`, `decision`, `checkpoint`, `user_check_in`, `failure`, `note`
- `message`
- `metadata_json`
- `created_at`

Batch step replacement and significant status changes should create events automatically.

### Checkpoints

Checkpoints are compact recovery cards.

Fields:

- `checkpoint_id`
- `goal_id`
- `step_id` nullable
- `summary`
- `current_state`
- `next_actions_json`
- `open_questions_json`
- `risks_json`
- `metadata_json`
- `created_at`

The latest checkpoint should be easy to fetch with the goal. Checkpoints should be mergeable into later chat compaction, but `goal_ops` does not replace chat compaction.

## Operations

Use batch operations from day one to avoid mechanical tool-call churn.

### Goal Operations

- `create_goal`
- `update_goal`
- `get_goal`
- `list_goals`

`create_goal` may accept initial steps in the same call and should return all ids.

### Step Operations

- `replace_steps`
- `update_steps`
- `list_steps`

`replace_steps` semantics:

- Runs in one transaction.
- Replaces the active plan in one call.
- Does not silently delete completed historical steps. Superseded active steps should be marked `superseded`.
- Assigns sparse positions when omitted.
- Creates a `plan_changed` event.
- Returns the resulting ordered step list with ids.

`update_steps` semantics:

- Runs in one transaction.
- Accepts multiple step patches.
- Can update status, position, title, summary, and metadata.
- Creates status/plan events for significant changes.
- Returns the resulting ordered step list.

### Event and Checkpoint Operations

- `add_events`
- `checkpoint`
- `list_events`
- `get_latest_checkpoint`

`add_events` should accept a batch. `checkpoint` should create both a checkpoint row and a compact event row.

### Session and Workspace Relationship

Goals are not owned by chat sessions. Do not add a session-level `active_goal_id` unless a concrete later workflow proves it is necessary. Unlike workspace, a goal is a durable record with its own id, status, steps, checkpoints, source provenance, and related file activity. Storing a second active-goal pointer on the session would duplicate authority and create switching, clearing, stale-pointer, and disagreement semantics that are not needed yet.

Chat-originated goals remain discoverable by source provenance: `source_type="chat"` plus the session id as `source_id`. Workflow- and context-originated goals should pass goal ids programmatically when they continue work under a goal.

`workspace_path_hint` should mirror the existing AssistantMD convention: it is a session/context-script hint that can be used or ignored by the default composition. There should be no `workspaces` table and no required workspace identity in `goal_ops`.

Default composition should not auto-select or inject goals every turn yet. The first durability layer for chat-originated goal continuity is normal agent use of `goal_ops` plus chat compaction preserving relevant goal ids, names, checkpoints, next actions, and open questions. If that proves insufficient, a default or user-authored context script can later query `goal_ops` by source, workspace hint, name, or status and inject a compact goal card into every turn.

Goal source provenance is owned by the runtime/tool layer, not by the model payload. `create_goal` should infer source fields from the active runtime:

- `chat`: source id is the chat session id.
- `workflow`: source id is the workflow global id.
- `context`: source id is the context global id, currently `{vault_name}/context/{template_name}/{session_id}`.

The active execution task id should be captured as `source_task_id` when available. User- or model-supplied `source_*` fields in the goal payload should not determine provenance.

### Related File Activity

Do not add `attach_artifact`, `record_artifact_ref`, or an artifact table initially.

Instead:

- Extend the existing task/mutation context so execution tasks can carry `goal_id` and optionally `step_id`.
- Persist goal context through the existing vault mutation recorder.
- Add a query operation such as `list_related_files` or `list_activity` that derives related files from existing `task_file_mutations` grouped by goal context.

This keeps file provenance canonical in the vault-state mutation system.

## Existing Hooks to Reuse

`goal_ops` should use existing extension points rather than adding parallel registries or dispatch paths.

- Tool implementation should subclass `core.tools.base.BaseTool` and implement `get_tool(...)` plus `get_instructions()`.
- Tool discovery should flow through the settings-backed registry in `system/settings.yaml` / `core.settings.store`, with a `settings.template.yaml` entry mapping `goal_ops` to `core.tools.goal_ops`.
- Tool binding should remain centralized in `core.authoring.shared.tool_binding.resolve_tool_binding(...)`, which imports the configured module, finds the `BaseTool` subclass, wraps the Pydantic AI tool, and returns `ToolReturn` metadata.
- Chat/delegate/direct-tool exposure should continue through `core.llm.capabilities.assistant_tools.build_assistant_tools_capabilities(...)`; `goal_ops` should not be manually appended elsewhere.
- Tool visibility in system instructions should come from the settings registry one-line description. Full usage should live in `docs/tools/goal_ops.md`, readable through `__virtual_docs__/tools/goal_ops.md`. `get_instructions()` may remain as a minimal compatibility fallback, but it should not be treated as the primary instruction surface.
- Structured tool failures should use the existing `core.tools.failures` envelope where applicable, returning model-visible failure metadata instead of throwing raw errors for expected user/actionable cases.
- File mutations caused while pursuing a goal should keep using `core.vault_state.file_mutations` and the execution-task mutation recorder. `goal_ops` should not write files directly or create another artifact path.
- Goal context propagation should extend existing execution task metadata/context rather than adding a separate process-local task tracker.

## Affected Areas

Expected implementation surfaces:

- New goal persistence module, likely under `core/goals/`.
- System database migrations for goal tables.
- Tool module under `core/tools/goal_ops.py`.
- Settings-backed tool registry entry in `system/settings` templates.
- Tool instruction documentation for `goal_ops`.
- Execution task context or metadata propagation for `goal_id` and `step_id`.
- Vault-state task mutation schema/API extension for goal context.
- Architecture docs for goal ops and mutation provenance.
- System instruction and context-composition audit across default templates, tool docs, and user-owned playbooks.
- Deterministic validation scenarios under `validation/scenarios/integration/core/`.

## Instruction Audit

Goal tracking will eventually need to be folded into the instruction stack, but the exact prompt and composition details should be decided after the initial `goal_ops` behavior exists.

Audit decisions so far:

- `goal_ops` tool docs are the primary tool-usage instruction surface.
- Global system instructions need little or no goal-specific change while the tool-doc lookup contract remains in place.
- Do not add session-level active goal metadata in the default design.
- Do not change default context goal injection yet.
- Audit chat compaction next, because compaction is the first durability layer for preserving goal orientation in long-running chat sessions.

Remaining surfaces to review:

- `goal_ops` tool instruction doc and virtual-doc exposure.
- Default system/context templates, only if compaction and agent-driven `goal_ops` lookup prove insufficient.
- User-owned workspace playbooks such as `README.md`, `playbook.md`, or `goal.md` conventions.
- Workflow/context scripts that may create, update, or surface goals.
- Compaction prompts, to ensure goal ids/names, checkpoints, next actions, and open questions are preserved when they matter.

The audit should preserve the existing AssistantMD philosophy: core instructions may provide softly opinionated defaults, while user-owned playbooks decide how goals are used in a particular vault or workspace convention.

## Validation Target

Add a deterministic core integration scenario, tentatively:

```text
validation/scenarios/integration/core/goal_ops.py
```

Assertions:

- Creating a goal with initial steps persists the goal and returns step ids.
- Step ordering is controlled by `position`, not id or title.
- `replace_steps` updates the active plan atomically and marks removed active steps `superseded`.
- `update_steps` can batch status and position changes.
- Events are recorded for creation, plan replacement, and checkpoint creation.
- Latest checkpoint is returned with expected structured fields.
- `goal_ops` does not create files or artifact rows.

Add or extend a vault mutation scenario after goal context propagation exists:

- A file mutation performed during a goal-scoped task records `goal_id` and `step_id`.
- Related goal files are derived from task mutation rows.
- Existing task mutation grouping remains backward compatible for non-goal tasks.

## Rollout Phases

Current status: Phase 1 and the first Phase 2 provenance slice are implemented on this branch. Phase 3 remains planned follow-up.

### Phase 1: Ledger Only

- Add goal, step, event, and checkpoint persistence.
- Add `goal_ops` tool operations for goals, batch steps, events, and checkpoints.
- Add deterministic scenario coverage for `goal_ops` behavior.
- Do not touch file mutation provenance yet.

### Phase 2: Goal Context Propagation

- Add goal context to execution tasks or task metadata.
- Persist goal context into task file mutation rows.
- Add `goal_ops` related activity query backed by existing mutation records.
- Extend validation to prove files are related by mutation provenance, not a parallel artifact table.

### Phase 3: Default Composition

- Audit and, if needed, revise chat compaction prompts so goal orientation survives long-running chat compaction.
- Leave goal lookup agent-driven through `goal_ops` unless validation or real use shows the model loses goal orientation after compaction.
- Defer default context goal injection. If needed later, implement it as a composable context-script policy that queries `goal_ops` and injects a compact goal card, not as session-owned goal authority.
- Optionally write or update workspace markdown such as `goal.md` from normal file tools/workflows.
- Keep markdown conventions user-editable.
- Complete the system instruction audit without hard-coding a single workflow style.

## Next Phase

Move to Feature Development for Phase 2 only: propagate optional `goal_id` and `step_id` through existing execution task/mutation context so related files can be derived from vault mutation activity. Do not add an artifact table or a parallel file mutation path.
