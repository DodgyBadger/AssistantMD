# Execution Task Coordinator Plan

## Goal

Introduce a lightweight, in-process execution task coordinator for AssistantMD.

This is the shared host-level lifecycle layer for cancellable and governable work such as:

- chat responses
- workflow executions
- workflow tests
- future context compaction or background maintenance tasks

Avoid using `run` as the primary noun for this layer. Pydantic AI already uses agent runs as an inner execution concept. AssistantMD should call the host-level unit an **execution task**.

## Problem

Today, long-running work is owned directly by its caller:

- chat endpoints call Pydantic AI directly
- scheduled workflows are triggered by APScheduler jobs
- manual workflow execution and `workflow_run` each call the authoring runtime path directly

That makes cancellation, status, timeout, overlap decisions, and future queue handling hard to implement consistently.

Issues this plan supports:

- #32 workflow governor
- #33 active chat cancellation
- #34 async `workflow_run` contract

## Design Direction

Add one process-local coordinator that tracks active execution tasks by id and scope.

The coordinator is not a durable task system. It does not resume interrupted work after restart.

Runtime truth:

- active handles live in memory
- status is queryable while the app process is alive
- terminal outcomes are logged
- optional lightweight history can be added later, but it is not required for the first slice

Startup recovery:

- after process restart, no active or queued task state is restored
- interrupted scheduled workflows can wait for the next tick or be started manually
- interrupted manual/chat work can be retried by the user

## Core Concepts

### ExecutionTask

One active or recently terminal unit of work.

Suggested fields:

- `task_id`
- `kind`: `chat`, `workflow`, `workflow_test`, `maintenance`
- `scope`: e.g. `chat_session:<id>`, `vault:<name>`, `global`
- `status`: `queued`, `running`, `completed`, `failed`, `cancelled`, `timed_out`, `skipped`
- `label`: user-readable summary
- `created_at`, `started_at`, `finished_at`
- `source`: `api`, `scheduler`, `tool`, `system`
- `cancel_requested`
- `terminal_reason`
- `latest_event`
- internal active `asyncio.Task` handle when running

### TaskCoordinator

Owns task registration, status transitions, cancellation requests, and active task lookup.

Responsibilities:

- create task ids
- register active work
- mark terminal states
- expose status snapshots
- cancel active tasks by id or scope
- clean up stale terminal records from memory

Non-goals:

- durable queue recovery
- distributed worker coordination
- restart/resume semantics
- workflow overlap policy

### WorkflowGovernor

Uses `TaskCoordinator` but owns workflow-specific policy.

Responsibilities:

- route all workflow execution entry points through one lane
- enforce per-vault single active workflow execution
- decide overlap policy
- expose workflow status, cancel, and flush hooks
- apply workflow timeout policy

Initial overlap policy should be conservative and simple. Prefer `skip` first unless backlog behavior is explicitly needed.

## Runtime Bootstrap Integration

`RuntimeContext` should own the coordinator, because it already owns long-lived process services.

Proposed additions:

- `core/runtime/execution_tasks.py` or `core/execution/tasks.py`
- `RuntimeContext.task_coordinator`
- optionally `RuntimeContext.workflow_governor`

Bootstrap sequence:

1. initialize scheduler, workflow loader, ingestion service as today
2. create `TaskCoordinator`
3. create `WorkflowGovernor`
4. attach both to `RuntimeContext`
5. set global runtime context
6. reload workflow jobs
7. resume scheduler

Shutdown:

- request cancellation for active tasks
- cancel active asyncio handles
- mark unfinished in-memory tasks as cancelled/interrupted for logging
- clear runtime context as today

## Pydantic AI Boundary

Pydantic AI owns inner agent execution:

- `Agent.run(...)`
- `Agent.run_stream_events(...)`
- usage limits
- model/tool execution
- history processor behavior

AssistantMD owns host lifecycle:

- task id
- active task lookup
- cancellation endpoint
- status endpoint
- workflow overlap policy
- queue/skip decisions
- UI state

The coordinator should wrap Pydantic AI calls rather than replacing them.

## Workflow Integration

Current workflow execution entry points:

- APScheduler job function
- manual `/api/workflows/execute`
- `workflow_run(operation="run")`

Target shape:

```python
await runtime.workflow_governor.execute_workflow(
    global_id=global_id,
    source="scheduler" | "api" | "tool",
    step_name=step_name,
)
```

APScheduler remains a trigger source. It should not be the final overlap authority.

Manual API and tool execution should use the same governor path as scheduled execution.

## Chat Integration

Chat execution should register a task scoped to the chat session.

Non-streaming path:

- wrap the call to `prepared.agent.run(...)`
- expose cancellation by task id or chat session id

Streaming path:

- wrap the async stream around `prepared.agent.run_stream_events(...)`
- mark task status when stream completes or fails
- handle cancellation by stopping the stream and cancelling the underlying active handle
- return a deterministic cancellation SSE event if possible

Initial chat policy:

- one active chat task per chat session
- cancellation targets the active task for that session
- no queueing for chat responses in the first slice

## Cancellation Model

Cancellation should be cooperative where possible and forceful where needed.

Mechanisms:

- coordinator marks `cancel_requested=True`
- active `asyncio.Task.cancel()` is called
- tools and workflow helpers can later inspect a cancellation token for cooperative exits
- terminal state becomes `cancelled` when cancellation is observed

Long-running local operations may not stop immediately in the first slice. The contract should say cancellation is best-effort but deterministic in state transition once control returns.

## Timeout Model

Timeout is a policy above execution.

Workflow timeout belongs in the workflow governor and should apply to:

- scheduled workflow execution
- manual workflow execution
- `workflow_run` execution

Chat timeout can be considered separately; current model/provider/API timeouts may already cover part of that behavior.

## API Sketch

Possible endpoints:

- `GET /api/tasks`
- `GET /api/tasks/{task_id}`
- `POST /api/tasks/{task_id}/cancel`
- `GET /api/chat/sessions/{session_id}/active-task`
- `POST /api/chat/sessions/{session_id}/cancel`
- `GET /api/workflows/tasks?vault_name=...`

Names can change, but the endpoint language should use `task`, not `run`.

## Tool Contract Sketch

Future `workflow_run` operations:

- `run`: existing blocking behavior initially, later can delegate to governor
- `start`: starts async workflow task and returns `task_id`
- `status`: returns task status/events
- `cancel`: requests cancellation

Issue #34 should stay focused on the async external contract after the governor foundation exists.

## Validation Targets

Initial targeted scenarios:

1. Chat cancellation
   - start a controllable long-running chat/tool path
   - cancel by session/task
   - assert terminal `cancelled` state and UI/API response shape

2. Workflow governor overlap
   - trigger scheduled-style workflow execution and manual execution for same vault
   - assert one active workflow task per vault
   - assert configured overlap decision is logged

3. Cross-vault concurrency
   - start workflows in two vaults
   - assert both can execute concurrently

4. `workflow_run` status foundation
   - start or execute through governor
   - assert status snapshot includes task id, kind, scope, source, and terminal status

Maintainers own full validation suite execution.

## First Implementation Slice

Recommended first slice:

1. Add `TaskCoordinator` and attach it to `RuntimeContext`.
2. Add status/cancel primitives with no UI.
3. Route manual workflow API execution through `WorkflowGovernor`.
4. Route `workflow_run(operation="run")` through the same governor.
5. Route APScheduler workflow jobs through the same governor.
6. Add overlap decision logging.
7. Add one focused overlap validation scenario.

Chat cancellation can be the second slice if that keeps the workflow governor smaller.

## Open Questions

- Should initial workflow overlap policy be `skip` or `queue`?
- Should terminal task snapshots be kept only in memory, or also written to a small history table?
- Should chat cancellation and workflow cancellation share the same public endpoint family immediately, or start with feature-specific endpoints?
- Should context compaction be modeled now, or left as a future task kind?
- What should the UI show for active workflow tasks before async `workflow_run` exists?
