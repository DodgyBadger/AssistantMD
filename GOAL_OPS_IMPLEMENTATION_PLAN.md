# Goal Ops Implementation Plan

## Purpose

Add a small `goal_ops` persistence primitive for longer knowledge-work tasks. The tool lets an agent durably record a goal, a lightweight plan snapshot, compact checkpoints, source provenance, and goal-scoped file mutation activity while leaving actual execution to existing chat, workflow, file, and vault systems.

This is not a new autonomous mode, scheduler, planner, project-management subsystem, or artifact pipeline. It is a coordination primitive the default composition can use when a task is too large to keep only in chat history.

## Design Principles

- Markdown remains the user-facing work surface. Workspace files such as `goal.md`, `README.md`, or `playbook.md` are default composition choices, not mandatory authority.
- Goals belong to a vault. Any workspace path is only a hint for default composition and filtering, not a first-class workspace owner or required scope.
- SQLite is the runtime source of truth for exact ids, status, source provenance, checkpoints, and the current lightweight plan snapshot.
- `goal_ops` records state; it does not decide what work to do next.
- File creation and mutation remain owned by existing vault/file pathways.
- Goal-scoped file activity is derived from existing task file mutation activity, using goal context on the execution task or mutation rows. `goal_ops` does not create a separate artifact table or write files directly.
- Tool execution is not automatically retried by `goal_ops`. Tool failures remain model-visible decision inputs.

## Data Shape

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
- `plan_json`: optional compact JSON snapshot of the current plan
- `success_criteria_json`
- `metadata_json`
- `created_at`
- `updated_at`

`blocked` is treated as resumable unless a later workflow needs terminal blocked semantics.

### Plan Snapshot

Do not model steps as first-class durable rows in the public tool contract. A goal may carry a lightweight `plan_json` value instead: a short markdown string, a list of task objects, or another compact JSON shape that helps the agent resume work.

The plan snapshot is replaced through `update_goal`. It is not a project-management subsystem: no stable step ids, no step event history, no required ordering schema, and no nested durable task graph. Detailed work logs and artifacts belong in normal vault markdown.

### Events

Events are goal-level audit entries. They should be useful for transparency and future summarization, not noisy traces of every internal operation.

Events are created automatically for goal creation, meaningful goal updates, and checkpoints. Manual event operations are not part of the public tool contract for now.

### Checkpoints

Checkpoints are compact recovery cards.

Fields:

- `checkpoint_id`
- `goal_id`
- `summary`
- `current_state`
- `next_actions_json`
- `open_questions_json`
- `risks_json`
- `metadata_json`
- `created_at`

`get_goal` includes the latest checkpoint so a separate latest-checkpoint operation is unnecessary.

## Operations

Keep operations small and goal-centered:

- `create_goal`
- `update_goal`
- `get_goal`
- `list_goals`
- `checkpoint`
- `list_activity`

`create_goal` and `update_goal` may accept a compact `plan` value. `list_goals` supports ordinary filters by status, query, workspace hint, and semantic chat-session source filters such as `data.source="current_session"`.

## Session and Workspace Relationship

Goals are not owned by chat sessions. Do not add a session-level `active_goal_id` unless a concrete later workflow proves it is necessary. Unlike workspace, a goal is a durable record with its own id, status, plan snapshot, checkpoints, source provenance, and related file activity. Storing a second active-goal pointer on the session would duplicate authority and create switching, clearing, stale-pointer, and disagreement semantics that are not needed yet.

Chat-originated goals remain discoverable by source provenance: `source_type="chat"` plus the session id as `source_id`. Workflow- and context-originated goals should pass goal ids programmatically when they continue work under a goal.

`workspace_path_hint` mirrors the existing AssistantMD convention: it is a session/context-script hint that can be used or ignored by the default composition. There should be no `workspaces` table and no required workspace identity in `goal_ops`.

Default composition should not auto-select or inject goals every turn yet. The first durability layer for chat-originated goal continuity is normal agent use of `goal_ops` plus chat compaction preserving relevant goal ids. If that proves insufficient, a default or user-authored context script can later query `goal_ops` by source, workspace hint, name, or status and inject a compact goal card into every turn.

Goal source provenance is owned by the runtime/tool layer, not by the model payload. `create_goal` infers source fields from the active runtime:

- `chat`: source id is the chat session id.
- `workflow`: source id is the workflow global id.
- `context`: source id is the context global id, currently `{vault_name}/context/{template_name}/{session_id}`.

The active execution task id is captured as `source_task_id` when available. User- or model-supplied `source_*` fields in the goal payload do not determine provenance.

## File Activity

Do not add `attach_artifact`, `record_artifact_ref`, or an artifact table.

Instead:

- Execution tasks may carry `goal_id` and optionally `step_id` for lower-level/internal callers.
- Vault mutation rows persist goal context through the existing mutation recorder.
- `list_activity` returns existing `task_file_mutations` grouped by goal context. The model can derive the file list it needs from that broader activity result.

This keeps file provenance canonical in the vault-state mutation system.

## Existing Hooks to Reuse

`goal_ops` should use existing extension points rather than adding parallel registries or dispatch paths.

- Tool implementation subclasses `core.tools.base.BaseTool`.
- Tool discovery flows through the settings-backed registry in `system/settings.yaml` / `core.settings.store`.
- Tool binding remains centralized in `core.authoring.shared.tool_binding.resolve_tool_binding(...)`.
- Chat/delegate/direct-tool exposure continues through `core.llm.capabilities.assistant_tools.build_assistant_tools_capabilities(...)`.
- Tool visibility in system instructions comes from the settings registry one-line description. Full usage lives in `docs/tools/goal_ops.md`, readable through `__virtual_docs__/tools/goal_ops.md`.
- Structured tool failures use the existing `core.tools.failures` envelope where applicable.
- File mutations caused while pursuing a goal keep using `core.vault_state.file_mutations` and the execution-task mutation recorder.
- Goal context propagation extends existing execution task metadata/context rather than adding a separate process-local task tracker.

## Instruction Audit

Instruction alignment for the current scope is complete:

- `goal_ops` tool docs are the primary tool-usage instruction surface.
- The default fallback playbook explains when to use `goal_ops` and discourages goal creation for mundane tasks.
- Chat compaction and session summary prompts preserve exact `goal_id` values when present.
- Global system instructions need little or no goal-specific change while the tool-doc lookup contract remains in place.
- Do not add session-level active goal metadata in the default design.
- Do not change default context goal injection yet.

If compaction and agent-driven `goal_ops` lookup prove insufficient, revisit default or user-authored context-script goal injection as a composable policy.

## Validation Target

Deterministic core scenario:

```text
validation/scenarios/integration/core/goal_ops.py
```

Assertions:

- Creating a goal with a compact plan persists the goal and returns the goal id.
- `update_goal` can replace the plan snapshot.
- Source provenance is inferred and model-supplied source fields do not determine provenance.
- `list_goals` can filter by status, query, workspace hint, and semantic session source.
- `get_goal` returns the latest checkpoint.
- A file mutation performed during a goal-scoped task records `goal_id`.
- Goal file activity is derived from task mutation rows.
- `goal_ops` does not create files or artifact rows.

## Rollout Phases

Current status: goal persistence, lightweight plan snapshots, source provenance, mutation provenance, and instruction alignment are implemented on this branch.

### Phase 1: Lightweight Ledger

- Add goal, plan snapshot, event, and checkpoint persistence.
- Add `goal_ops` tool operations for goals, checkpoints, and related activity.
- Add deterministic scenario coverage for `goal_ops` behavior.

### Phase 2: Goal Context Propagation

- Add goal context to execution tasks or task metadata.
- Persist goal context into task file mutation rows.
- Add `goal_ops` related activity query backed by existing mutation records.
- Extend validation to prove goal activity is backed by mutation provenance, not a parallel artifact table.

### Phase 3: Default Composition

- Audit and revise chat compaction/session summary prompts so exact goal ids survive long-running chat compaction.
- Leave goal lookup agent-driven through `goal_ops` unless validation or real use shows the model loses goal orientation after compaction.
- Defer default context goal injection. If needed later, implement it as a composable context-script policy that queries `goal_ops` and injects a compact goal card, not as session-owned goal authority.
- Keep markdown conventions user-editable.

## Next Phase

Move to cleanup/review readiness unless real use reveals a missing goal retrieval or context-composition affordance. Do not add first-class step rows, an artifact table, or session-owned active goal state without a concrete workflow that requires it.
