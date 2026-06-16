# 0004 - Track Long Running Work With Process Local Execution Tasks

## Status

Accepted, backfilled.

## Context

Chat, workflows, ingestion, code execution, and history compaction can take long
enough that the UI and API need visibility into active work. Some operations
also need cancellation, timeout handling, lifecycle validation events, and task
identity for vault mutation provenance.

## Decision

Use a process-local `TaskCoordinator` owned by `RuntimeContext` to track active
and recently terminal execution tasks. Use `WorkflowGovernor` as the workflow
policy layer for vault execution lanes, workflow timeout, lifecycle metadata,
and workflow task registration.

## Rationale

The first durable need was runtime visibility and cancellation, not a persistent
job history. A process-local coordinator gives active tasks a consistent status
model and cancellation handle without turning every operation into a durable job
queue. Keeping workflow policy in a governor avoids duplicating workflow
execution rules across scheduler, API, and tool paths.

## Consequences

- Task snapshots are runtime state, not a permanent system of record.
- Long-running entrypoints should register through the coordinator.
- Terminal task history is bounded.
- Vault mutation rows can persist task identity even though task snapshots
  themselves are process-local.
- Cancellation needs explicit handling so cancelled work is not reported as a
  generic failure.

## Evidence

- Current contract: `docs/architecture/execution-tasks.md`,
  `docs/architecture/runtime.md`
- Recovered sources: PR #41
  `EXECUTION_TASK_COORDINATOR_IMPLEMENTATION_PLAN.md`,
  `EXECUTION_TASK_COORDINATOR_PLAN.md`, `CHAT_HISTORY_COMPACTION_SPEC.md`
