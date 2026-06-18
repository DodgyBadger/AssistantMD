# 0019 - Centralize Runtime Execution Task Running

## Status

Accepted.

Supersedes the workflow-specific execution-policy portions of
[0014 - Govern Workflow Execution Through Vault Lanes](0014-workflow-governor-vault-lanes.md).

Amends [0004 - Track Long Running Work With Process Local Execution Tasks](0004-process-local-execution-tasks.md)
by separating task state coordination from task running policy.

## Context

AssistantMD now exposes long-running work through shared execution-task UI and
API surfaces. Chat, workflows, ingestion, compaction, vault-state refresh, and
future external chat surfaces all need consistent cancellation, lifecycle
visibility, task identity, and background ownership.

The existing architecture already centralizes task state in `TaskCoordinator`.
It tracks active and recently terminal work, cancellation handles, lifecycle
events, task metadata, and current-task context for vault mutation provenance.

However, task running policy is still split:

- `WorkflowGovernor` owns workflow task spawning, vault lanes, global workflow
  concurrency, workflow timeout wrapping, and workflow-specific metadata.
- `core/chat/task_execution.py` creates chat background asyncio tasks directly
  and owns per-session queueing.
- `core/ingestion/worker.py` creates ingestion child asyncio tasks directly.
- `RuntimeContext.start_background_vault_state_refresh(...)` creates a direct
  background asyncio task.
- compaction and API-triggered ingestion run inline under task contexts.

That split makes drift likely. Cancellation, runtime-loop ownership, timeout
handling, queue metadata, and shutdown behavior can diverge by task kind even
though those concerns are not inherently workflow-specific or chat-specific.

## Decision

Introduce a runtime-owned `ExecutionTaskRunner` as the generic execution policy
layer for AssistantMD execution tasks.

The architecture has three layers:

1. `TaskCoordinator`
   - owns process-local task state
   - owns task status transitions and cancellation handles
   - owns lifecycle validation events
   - owns current-task context for mutation provenance

2. `ExecutionTaskRunner`
   - owns generic task running mechanics
   - schedules detached work onto the runtime background loop
   - attaches asyncio handles to queued task records immediately
   - registers background handles for runtime shutdown
   - applies optional timeout policy
   - applies optional lane/concurrency gates
   - preserves cancellation semantics across queued, preflight, running, and
     timeout states
   - supports inline task contexts for work that intentionally completes inside
     the current request/tool call

3. Domain adapters
   - own domain-specific work and side effects
   - supply task identity, metadata, queue keys, timeout settings, and optional
     lifecycle hooks
   - produce domain-specific results such as workflow result metadata, chat SSE
     events, ingestion job statuses, compaction summaries, and vault-state
     refresh logs

Workflow vault lanes and workflow timeout remain required behavior, but they
should be implemented through the generic runner policy rather than private
workflow-only primitives. `WorkflowGovernor` may remain as a workflow adapter
while it still contains workflow-specific result shaping, failure metadata, and
logging. It should no longer be the owner of generic background spawning, lane
locking, or timeout mechanics after the runner migration is complete.

Chat session serialization should likewise use the generic lane/gate policy
once available. Chat-specific behavior remains in chat code: transcript
persistence, model preflight, event buffering, SSE payloads, latest-turn failure
markers, and surface adapter contracts.

## Rationale

Task type differences are real, but most execution mechanics are shared.
Spawning, cancellation, timeout, queueing, lane locks, background handle
tracking, and shutdown behavior should not have separate implementations per
task type.

Centralizing those mechanics reduces drift and makes later capabilities easier:

- durable/replayable task watcher UI
- consistent cancellation for queued and preflight work
- long-running chat turns that survive browser disconnects
- future external chat surfaces such as Telegram or Discord
- consistent validation scenarios for task lifecycle behavior
- clearer ownership between runtime infrastructure and domain behavior

Keeping domain adapters thin also avoids putting workflow result schemas or chat
SSE details into the runtime runner.

## Evidence

- Plan: `EXECUTION_TASK_RUNNER_REDESIGN_PLAN.md`
- Current task state contract: `docs/architecture/execution-tasks.md`
- Runtime composition contract: `docs/architecture/runtime.md`
- Prior decisions:
  - [0004 - Track Long Running Work With Process Local Execution Tasks](0004-process-local-execution-tasks.md)
  - [0014 - Govern Workflow Execution Through Vault Lanes](0014-workflow-governor-vault-lanes.md)
