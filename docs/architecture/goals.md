# Goals

Goals are lightweight durable records for longer knowledge-work tasks that are
too large, interruptible, or tool-heavy to track only in chat history. They are
implemented by `core/goals/` and exposed to agents through `goal_ops`.

## Responsibility

`goal_ops` records state. It does not execute work, schedule work, write files,
attach artifacts, or decide what the agent should do next. Chat, workflows,
`code_execution`, file tools, and user-authored scripts remain responsible for
doing the actual work.

Goals provide:

- stable goal ids;
- vault ownership and optional workspace path hints;
- system-owned source provenance;
- status, objective, success criteria, and a lightweight plan snapshot;
- compact recovery checkpoints;
- goal events for meaningful updates;
- related file activity derived from existing vault mutation records.

## Source Of Truth

SQLite is the source of truth for operational goal state: exact ids, status,
source provenance, checkpoints, timestamps, and the current lightweight plan
snapshot.

Markdown remains the user-facing work surface. Workspace files such as
`goal.md`, `progress.md`, `sources.md`, drafts, `README.md`, and `playbook.md`
are default composition choices or user conventions, not mandatory goal
databases. User edits to markdown are treated as context and instructions. They
do not automatically mutate goal state unless a workflow, context script, or
agent deliberately reads the files and calls `goal_ops`.

## Data Model

Goals belong to a vault. `workspace_path_hint` is a non-authoritative
vault-relative hint for filtering and default composition. There is no
workspace table or required workspace identity in the goal subsystem.

Goal records include:

- `goal_id`;
- `vault_name`;
- optional `workspace_path_hint`;
- optional source fields inferred by the runtime;
- `title` and `objective`;
- `status`;
- optional `plan_json`;
- optional success criteria and metadata;
- timestamps.

The public contract does not model steps as durable first-class rows. A goal may
carry a compact `plan_json` snapshot: a short markdown string, a list of task
objects, or another small JSON shape that helps an agent resume work. Detailed
work logs and rich project structure belong in normal vault markdown.

Checkpoints are compact recovery cards. `get_goal` returns the latest
checkpoint, so there is no separate latest-checkpoint operation.

## Source Provenance

Goal source provenance is owned by the runtime/tool layer, not by model payloads.
When a goal is created, `goal_ops` infers source fields from the active runtime:

- chat-created goals use source type `chat` and the chat session id;
- workflow-created goals use source type `workflow` and the workflow global id;
- context-created goals use source type `context` and the context global id.

The active execution task id is captured when available. User- or model-supplied
`source_*` fields do not determine provenance.

Goals are not owned by chat sessions. There is no session-level `active_goal_id`
in the default design. Chat-originated goals remain discoverable through source
provenance, and workflows or context scripts should pass goal ids
programmatically when they continue work under a goal.

## File Activity

`goal_ops` does not create an artifact table or write files directly. File
provenance stays canonical in the vault mutation system.

When work runs with goal context, execution tasks and mutation rows may carry
`goal_id` and optional lower-level step metadata. `goal_ops(list_activity)`
queries existing `task_file_mutations` to show goal-related mutation groups and
paths.

## Composition

Default composition is intentionally light. Agents should use `goal_ops` for
complex, durable, or interruptible work, and should avoid creating goals for
ordinary questions or quick edits. Chat compaction and session summaries preserve
exact goal ids when they appear in a session.

Default context does not auto-select or inject active goals every turn. If
agent-driven lookup and compaction prove insufficient for a user workflow, a
default or user-authored context script can query goals by source, workspace
hint, name, or status and inject a compact goal card as context.

## Validation

The deterministic scenario
`validation/scenarios/integration/core/goal_ops.py` covers goal creation,
updates, source provenance, filtering, checkpoints, mutation-backed activity,
cleanup, and logging.

