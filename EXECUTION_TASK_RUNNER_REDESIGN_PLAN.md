# Execution Task Runner Redesign Plan

## Purpose

AssistantMD already has one shared task state model through `TaskCoordinator`, but task execution policy is still split across subsystem-specific launch paths. The next architecture step is to add a shared runtime task runner so long-running work uses one place for spawning, queued attachment, cancellation, timeout, lane/concurrency gates, and background-task ownership.

This plan keeps domain behavior in domain modules while moving generic execution mechanics into `core/runtime`.

## Current State

`TaskCoordinator` is the shared process-local task registry. It owns task records, status transitions, cancellation handles, lifecycle events, bounded terminal history, and current-task context.

`WorkflowGovernor` currently owns workflow-specific execution and several generic execution concerns:

- background task spawning onto the runtime bootstrap loop
- per-vault lane locking
- optional global workflow concurrency
- timeout wrapping
- queued task creation and attachment
- workflow failure metadata

Chat task-owned streaming now uses `TaskCoordinator`, but `core/chat/task_execution.py` still creates background asyncio tasks directly. Chat also implements its own per-session queue and terminal stream-event handling.

Ingestion and compaction use `TaskCoordinator.track_current_task(...)`, but their concurrency/spawn behavior lives in their callers:

- `core/ingestion/worker.py` creates asyncio tasks for queued ingestion jobs.
- API-triggered ingestion runs inline under a task context.
- chat compaction runs inline after chat turns or API/tool calls.
- vault-state refresh uses `RuntimeContext.start_background_vault_state_refresh(...)` with direct `asyncio.create_task`.

The result is a shared task registry, not yet a shared task runner.

## Target Design

Add a generic `ExecutionTaskRunner` owned by `RuntimeContext`.

The runner should provide one public path for detached task execution:

- create queued task records
- schedule work onto the runtime background loop
- attach the asyncio handle immediately
- register handles in `runtime.background_tasks`
- use clean contextvars
- mark start/completion/failure/cancellation/timeout consistently
- apply optional queue gates before start
- apply optional timeout
- update heartbeat metadata while queued
- preserve cancellation semantics across queued, preflight, running, and timeout states

The runner should also provide a thinner context path for inline task execution where the caller intentionally waits for completion.

Domain modules should supply a small task spec and callbacks:

- `kind`
- `source`
- `scope`
- `label`
- `metadata`
- `coroutine factory`
- optional `timeout_seconds`
- optional lane/concurrency gates
- optional lifecycle hooks for domain-specific side effects

Domain-specific behavior remains outside the generic runner:

- workflow result construction and workflow failure metadata
- chat SSE events and transcript persistence
- ingestion job status updates
- compaction result persistence
- vault-state refresh result logging

## Important Invariants

- `/api/tasks`, `/api/tasks/{task_id}`, and `/api/tasks/{task_id}/cancel` keep their current contracts.
- Existing task IDs remain process-local, not durable.
- Terminal task history remains bounded.
- Vault mutation provenance still comes from `get_current_execution_task()`.
- Workflow lane semantics stay conservative: one workflow per vault at a time.
- Chat session runs stay serialized by session.
- Cancelling queued work must always produce a terminal task state and any domain-specific terminal signal, such as chat SSE `cancelled`.
- No full validation run is required from agents; maintainers own full validation.

## Proposed Runtime Types

Names are provisional.

- `ExecutionTaskSpec`
  - task identity and metadata
  - optional timeout
  - optional lane keys or gate policy
  - source/kind/scope/label

- `ExecutionTaskRunner`
  - `start_background(spec, run, hooks=None) -> ExecutionTaskSnapshot`
  - `run_inline(spec, run, hooks=None) -> result`
  - owns runtime-loop scheduling and background task tracking

- `ExecutionGatePolicy`
  - per-scope serialization
  - keyed lane locks
  - optional global/per-kind semaphores
  - queue heartbeat metadata

- `ExecutionTaskHooks`
  - `on_queued`
  - `on_started`
  - `on_completed`
  - `on_failed`
  - `on_cancelled`
  - `on_timed_out`

Hooks should be narrow and optional. The generic runner should not learn chat SSE payloads or workflow result schemas.

## Implementation Slices

### Slice 1: Introduce Runtime Background Spawner

Status: complete.

Goal: remove duplicated direct background spawning without changing task semantics.

Changes:

- Add a small runtime-owned background spawner helper.
- Move workflow's `_schedule_background_spawn(...)` behavior into the shared helper.
- Make chat task execution use the same helper.
- Make vault-state refresh use the helper.
- Keep `TaskCoordinator` calls where they are for now.

Validation:

- `integration/core/chat_task_session_queue`
- `integration/core/chat_task_event_stream_api`
- `integration/core/chat_stream_background_task`
- `integration/core/workflow_cancellation`
- smoke: `git diff --check`

Commit boundary:

- One commit after this slice.

### Slice 2: Add Generic Background Task Runner Shell

Status: complete.

Goal: centralize create-queued-task, attach-existing-task, background handle registration, and terminal exception handling.

Changes:

- Add `core/runtime/task_runner.py`.
- Add `ExecutionTaskSpec`.
- Add `ExecutionTaskRunner.start_background(...)`.
- Use `TaskCoordinator.create_queued_task(...)` and `track_existing_task(...)` internally.
- Preserve cancellation and broad-exception behavior currently used by workflow/chat wrappers.
- Wire `RuntimeContext` to own `task_runner`.

Validation:

- New focused unit/smoke test for runner start/cancel/fail behavior.
- Existing workflow and chat scenarios should still pass before migration if the runner is introduced unused.

Commit boundary:

- One commit after the runner shell is introduced and covered.

### Slice 3: Migrate Chat Background Streaming To Runner

Status: complete.

Goal: make chat task-owned streaming use the shared runner while preserving chat SSE behavior.

Changes:

- Replace `asyncio.create_task` in `core/chat/task_execution.py` with `ExecutionTaskRunner.start_background(...)`.
- Keep chat-specific queue wait, preflight, transcript persistence, SSE event buffer, and failure markers in chat code.
- Keep the fixed cancellation behavior from the previous slice: queued/preflight cancellation must publish terminal SSE.

Validation:

- `integration/core/chat_task_session_queue`
- `integration/core/chat_task_event_stream_api`
- `integration/core/chat_stream_background_task`
- `integration/core/chat_stream_failure_logging`
- `integration/core/chat_surface_adapter`

Commit boundary:

- One commit after chat migration and smoke tests.

### Slice 4: Extract Generic Gate/Queue Policy

Status: complete.

Goal: move lane locks and queue heartbeats out of workflow/chat-specific loops where possible.

Changes:

- Add keyed lane locking to the runner or a companion `ExecutionGatePolicy`.
- Support queue heartbeat metadata for queued tasks.
- Migrate chat session serialization to a generic per-scope gate.
- Migrate workflow vault lanes to the same gate.
- Keep workflow-specific global concurrency as either a generic semaphore policy or a workflow adapter option, depending on implementation fit.

Validation:

- `integration/core/chat_task_session_queue`
- `integration/core/workflow_cancellation`
- a workflow lane scenario if one exists; otherwise add/extend a scenario proving two same-vault workflow starts serialize and different-vault workflows can proceed according to global settings.

Commit boundary:

- One commit after gate policy migration.

### Slice 5: Move Workflow Timeout Into Runner

Status: complete.

Goal: make timeout enforcement generic while preserving workflow metadata.

Changes:

- Add optional timeout support to `ExecutionTaskSpec`.
- Runner marks `timed_out` on timeout.
- Workflow adapter supplies timeout classification/result metadata through `on_timed_out`.
- Remove direct `asyncio.wait_for(...)` and timeout task marking from `WorkflowGovernor`.

Validation:

- Existing workflow timeout/failure scenario if present.
- If no focused scenario exists, add one that configures a short workflow timeout and asserts:
  - task status is `timed_out`
  - task metadata includes `workflow_result`
  - task metadata includes classified `workflow_failure`

Commit boundary:

- One commit after timeout migration.

### Slice 6: Thin WorkflowGovernor Into WorkflowTaskAdapter

Status: complete.

Goal: leave workflow-specific behavior in workflow code and remove generic runner responsibilities.

Changes:

- Keep workflow ID normalization, workflow result metadata, workflow failure metadata, and workflow logging in workflow-specific code.
- Remove workflow-owned background spawning.
- Remove workflow-owned lane and timeout primitives once migrated.
- Rename only if it improves clarity after behavior is moved; avoid churn before then.

Validation:

- `integration/core/workflow_cancellation`
- workflow run tool scenario, especially `operation=start/status/cancel`
- API endpoint scenario covering manual workflow execution

Commit boundary:

- One commit after cleanup.

### Slice 7: Migrate Ingestion And Compaction Where It Helps

Status: in progress. Scheduled ingestion worker migration complete.

Goal: bring remaining long-running task types under the same runner where they are actually detached or cancellable.

Changes:

- Ingestion worker uses runner for scheduled job tasks instead of creating child asyncio tasks directly.
- API-triggered ingestion can remain inline through `run_inline(...)`.
- Compaction can use `run_inline(...)` for API/tool calls.
- Auto-compaction after chat turns should remain carefully sequenced unless we explicitly want detached compaction behavior.
- Vault-state refresh may become a system task if it should appear in the dashboard; otherwise it can use only the shared spawner.

Validation:

- ingestion scenarios covering scheduler/API paths
- chat compaction scenarios
- vault-state refresh scenario if task-visible behavior changes

Commit boundary:

- One commit after each task type migration if the diff is non-trivial.

### Slice 8: Documentation And ADR Update

Goal: make the architecture contract match the new design.

Changes:

- Update `docs/architecture/execution-tasks.md`.
- Update `docs/architecture/runtime.md`.
- Update `docs/architecture/scheduler.md` if workflow governor responsibilities change.
- Add a new ADR superseding or extending ADR 0004/0014:
  - `TaskCoordinator` remains task state.
  - `ExecutionTaskRunner` owns generic runtime execution policy.
  - domain adapters own domain-specific results and side effects.

Validation:

- docs-only review plus `rg` for stale claims such as workflow-only task policy.

Commit boundary:

- One commit after docs alignment.

## Risks And Mitigations

- Risk: changing task terminal behavior can affect rollback observers.
  - Mitigation: keep terminal status transitions in `TaskCoordinator`; add runner coverage for terminal observer invocation.

- Risk: hooks become a second framework inside the app.
  - Mitigation: keep hooks narrow and domain-driven; do not add hooks until a migration slice needs them.

- Risk: generic gates hide domain-specific queue semantics.
  - Mitigation: gate policy should expose explicit keys and metadata, not infer domain meaning.

- Risk: long-running chat behavior regresses.
  - Mitigation: keep chat SSE event buffer and transcript logic in chat code; migrate only spawn/lifecycle/gate mechanics.

- Risk: WorkflowGovernor rename churn distracts from behavior.
  - Mitigation: migrate behavior first, then rename only if the remaining class is clearly no longer a governor.

## Open Questions

- Should chat have a configurable task timeout, or should model/tool limits remain the only chat guardrail for now?
- Should vault-state refresh appear as an execution task in the dashboard, or only use shared background spawning?
- Should global concurrency be per-kind only, or should the runner support a named shared pool?
- Should queued task records expose a generic `waiting_for_task_id` contract, or keep per-domain metadata names?

## Next Phase

Move to Feature Development with Slice 1 only: introduce the shared runtime background spawner and migrate chat/workflow/vault-state refresh spawning without changing queue, timeout, or lane semantics.
