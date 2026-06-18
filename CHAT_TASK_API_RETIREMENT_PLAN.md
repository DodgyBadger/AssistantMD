# Chat Task API Retirement Plan

## Purpose

Make task-owned chat execution the only user-facing chat-turn path. Retire the
legacy `/api/chat/execute` chat-turn endpoint, including its `stream` flag and
the non-streaming chat executor path, while keeping non-streaming `agent.run(...)`
available for internal one-shot work such as compaction, delegate, and workflow
helpers.

## Current State

The web app already submits chat turns through:

- `POST /api/chat/tasks`
- `GET /api/chat/tasks/{task_id}/events`

That path creates a process-local chat execution task, serializes turns by chat
session, supports cancellation, buffers events, and can survive in-run browser
disconnects until the task reaches a terminal state.

The older `/api/chat/execute` endpoint still accepts both blocking JSON chat
turns and same-request SSE streaming via a `stream` flag. It is now mostly a
validation and compatibility surface. Keeping it means chat behavior can drift
between direct `agent.run(...)` execution and task-owned streaming execution.

## Target Design

User-facing chat turns use one canonical contract:

- submit a turn with `POST /api/chat/tasks`
- observe progress with `GET /api/chat/tasks/{task_id}/events`
- poll/cancel through `/api/tasks/{task_id}` and `/api/tasks/{task_id}/cancel`

External chat surfaces, such as Telegram or Discord, should use the same backend
contract and adapt event consumption to the surface. They may stream deltas,
batch edits, or wait for the terminal event before sending a final response.

Internal non-chat model work may continue to use `agent.run(...)` when the
contract is a complete artifact rather than a chat turn.

## Invariants

- Chat turns remain persisted in the canonical chat store.
- Chat session queueing remains per `chat_session:<session_id>`.
- Chat task cancellation still emits terminal task state and terminal stream
  event.
- Tool-call and model-request usage limits still produce structured failures.
- Image attachments, workspace path, context template, thinking, model, and tool
  selection remain supported by `/api/chat/tasks`.
- Compaction, delegate, workflows, and other internal one-shot model calls keep
  their non-streaming model-call behavior.

## Slices

### Slice 1: Add Validation Helpers For Canonical Chat Tasks

Status: complete.

Goal: stop new validation work from using `/api/chat/execute`.

Changes:

- Add scenario helper methods that start a chat task, consume buffered SSE
  events, and return a final text/session/task summary.
- Add helper support for expected error events.
- Migrate one representative scenario from `/api/chat/execute` to the helper.

Validation:

- migrated scenario
- `integration/core/chat_task_event_stream_api`

Commit boundary:

- One commit after helper and representative migration pass.

### Slice 2: Migrate Chat Behavior Scenarios

Goal: move validation coverage for chat behavior to `/api/chat/tasks`.

Changes:

- Migrate API, tool, persistence, code execution, delegate, cache, cancellation,
  and failure scenarios that currently call `/api/chat/execute` for chat turns.
- Keep direct helper-level tests only where they are explicitly testing internal
  functions.

Validation:

- migrated scenarios by feature area
- `integration/core/api_endpoints`
- `integration/core/chat_task_session_queue`

Commit boundary:

- One commit per coherent scenario group if the diff is large.

### Slice 3: Remove Legacy Chat Execute API

Goal: remove the obsolete user-facing chat-turn endpoint.

Changes:

- Remove `/api/chat/execute`.
- Remove `ChatExecuteRequest.stream` and `ChatExecuteResponse`.
- Remove `execute_chat_prompt_stream(...)`.
- Remove compatibility-only current-loop streaming workaround if no remaining
  caller needs it.
- Keep internal `agent.run(...)` usage for non-chat complete-result work.

Validation:

- `rg "/api/chat/execute"` only finds intentional historical docs, if any.
- `rg "execute_chat_prompt("` only finds direct internal tests that still need
  the function, or none if removed.
- focused chat task scenarios.

Commit boundary:

- One commit after endpoint and compatibility code removal.

### Slice 4: Documentation And Surface Adapter Notes

Goal: align architecture docs with the canonical task-owned chat contract.

Changes:

- Update chat session architecture docs.
- Update execution task docs if needed.
- Document external chat surface guidance: submit task, consume events, render
  according to surface capability.

Validation:

- docs stale-claim search for `/api/chat/execute`, `stream=true`,
  `non-streaming chat`, and `ChatExecuteResponse`.

Commit boundary:

- One docs-only commit.
