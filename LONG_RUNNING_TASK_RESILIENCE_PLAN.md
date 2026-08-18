# Long-Running Task Resilience Analysis and Implementation Plan

## Status

Phase 1 investigation is sufficient to define the recovery boundary. The
foundational dependency migration now targets Pydantic AI 2.19, Harness 0.13,
and Monty 0.0.21. Provider construction, chat stream consumption, context
history processing, and the Monty authoring runner have been adapted to their
current APIs. Harness capability adoption remains gated on feature parity. A
deterministic experimental probe records Pydantic AI's stream-failure
boundaries without contacting a provider.

## Objective

Make long-running chat work, especially child-agent work launched through the
`delegate` tool, tolerate transient upstream API disconnections without losing
the parent turn, duplicating side effects, or requiring the browser connection
to remain open.

## Current Contract

AssistantMD already separates a browser subscriber from chat execution:

- `POST /api/chat/tasks` creates a process-local execution task.
- The task owns the agent run independently of the SSE subscriber.
- `GET /api/chat/tasks/{task_id}/events` sends 15-second keepalives and accepts
  an `after_sequence` cursor for buffered replay.
- The browser reconnects to the event endpoint after a cleanly ended response
  while the task remains queued or running.
- A disconnected SSE subscriber does not cancel the task.
- Completed chat history is durable, but active task state and live event
  buffers remain process-local and are lost on a server restart.

The delegate path has a different upstream boundary:

- `DelegateTool` creates a child Pydantic AI agent and awaits
  `collect_response(...)` inside `asyncio.wait_for(...)`.
- `collect_response(...)` consumes one streamed child run to completion.
- The shared HTTP transport retries connection/request failures and retryable
  HTTP statuses while opening a request, up to three attempts.
- There is no AssistantMD-owned retry loop for an incomplete or disconnected
  response after streamed output has begun.
- A recognized provider/network failure becomes a failed tool return; an
  unclassified exception aborts the parent stream.
- The default delegate timeout is 120 seconds, independent of transport retry
  behavior.

## Codex Comparison

The inspected OpenAI Codex source at commit
`a1dc95d5afcbd3ccdebb611864ce94fa3d3e8e3d` uses multiple independent layers:

1. HTTP request retries cover retryable status and transport failures.
2. Response-stream retries cover dropped or incomplete sampling streams. The
   default retry budget is five, with backoff and visible reconnect status.
3. Ordinary connection failures can use an unbounded retry mode with delays
   increasing from 5 to 60 seconds without consuming the normal stream retry
   budget.
4. When configured, exhausted WebSocket retries can fall back to HTTPS and
   reset the stream retry counter.
5. Sampling retries rebuild input from the session's current history and attach
   pending executed-tool-call state before resubmitting, reducing the risk of
   blindly replaying already executed tools.
6. The app-server keeps thread execution/state separate from an individual UI
   transport connection and supports reconnecting/resuming a thread.

The important lesson is not a longer socket timeout. Codex treats client
observation, upstream sampling, tool execution state, and durable conversation
state as separate recovery boundaries.

## Gap Assessment

### Highest-confidence gap

AssistantMD's browser/SSE connection can recover, but a mid-stream provider
disconnect inside `delegate` cannot. The existing retry transport is too low in
the stack to guarantee recovery once response streaming has started.

### Additional limitations

- The browser reconnect loop has no bounded backoff or exception retry around a
  failed `fetch()` or `reader.read()`; it reconnects only when a stream ends
  normally.
- Cursor replay is process-local and capped at 500 events per task, so a slow or
  long-disconnected subscriber can miss early events. The final transcript is
  still the authoritative completed artifact.
- Process restart cancels active process-local chat and delegate work. Durable
  session history can support a new continuation, but there is no restart-safe
  active-run recovery.
- Retrying an entire child run is unsafe when the child can invoke mutating
  tools unless tool-call identity and completed outcomes are made replay-aware.

## Pydantic AI Framework Assessment

AssistantMD targets `pydantic-ai[mistral,xai]==2.19.0`,
`pydantic-ai-harness[code-mode]==0.13.0`, and `pydantic-monty==0.0.21`.
Dependency currency and adoption of individual Harness capabilities remain
separate decisions.

### Available in the target framework

- `AsyncTenacityTransport`, `RetryConfig`, and `wait_retry_after` are the native
  HTTP request retry layer and are already used by AssistantMD.
- `Agent.run_stream(...)` and `Agent.run_stream_events(...)` are the native run
  and event boundaries. Their `message_history`, `conversation_id`,
  `usage_limits`, `usage`, `retries`, `event_stream_handler`, and `capabilities`
  arguments should remain the orchestration inputs rather than creating a
  parallel agent protocol.
- Pydantic message types (`ModelRequest`, `ModelResponse`, `ToolCallPart`,
  `ToolReturnPart`, `RetryPromptPart`) and their `tool_call_id` values are the
  canonical history and tool-correlation model.
- `Hooks` exposes run, node, model-request, tool-validation, tool-execution, and
  error interception. These hooks should supply progress/effect observation
  before custom wrappers are considered.
- `on_node_run_error` receives a live
  `RunContext.messages` list at a stream failure. That list is already composed
  of Pydantic `ModelMessage` instances and is therefore the preferred in-memory
  recovery frontier. The run-level `on_run_error` context is not suitable for
  this purpose: it remained empty in the deterministic 2.19 probe.
- `on_node_run_error` may recover by returning a next graph node or terminal
  result, and `wrap_node_run` may invoke its handler more than once. These are
  generic graph-redirection primitives, not a packaged model-stream retry
  policy. In particular, Pydantic documents that `run_stream()` performs
  streaming before the node wrapper, so a bounded retry still needs explicit
  state, delay, deadline, usage, and replay-safety policy. Phase 2 should not
  depend on private graph-node construction to manufacture a retry.
- `ProcessEventStream` exposes model-stream and tool-execution events and is the
  preferred framework-native observation surface.
- Pydantic's tool/output retry budgets and `ModelRetry` correct model or tool
  behavior; they are not transport recovery. The documented contract explicitly
  says whole agent runs are not automatically retried.
- Pydantic AI includes Temporal, DBOS, and Prefect durable-execution
  integrations. Adopting one would be an architectural/runtime dependency
  decision, not a small retry helper.
- Harness supplies `SubAgents`, `StepPersistence`, compaction, context,
  `code_mode`, and other capabilities whose overlap with AssistantMD is subject
  to the parity gate below.

### Remaining application responsibility

Even current Pydantic documentation distinguishes HTTP, model, tool, output,
and model-request retries and states that Pydantic AI does not retry a whole
agent run automatically. A mid-consumption stream exception from
`run_stream(...)` propagates to the caller.
Therefore AssistantMD may still need a thin orchestration policy around a run,
but it should:

- consume and persist Pydantic-native events and messages,
- correlate effects by Pydantic `tool_call_id`,
- use Pydantic hooks/capabilities for observation,
- resume through `message_history` only at provider-valid boundaries, and
- avoid introducing replacement message, tool-call, retry, or subagent types.

## Proposed Scope

Implement resilience in phases, beginning with the narrow upstream stream gap.
Do not introduce a durable distributed job system in the first phase.

### Phase 1: Classify and reproduce

- Add a deterministic model-stream fault probe that disconnects after partial
  child output and before the terminal response event.
- Capture the exact exception types emitted by each supported Pydantic AI
  provider path.
- Distinguish failures before any response/tool event, after text only, and
  after a child tool call has started or completed.
- Add structured attempt, delay, provider, phase, and prior-progress fields to
  the existing model/delegate failure evidence design.
- Use `ProcessEventStream` or `event_stream_handler` plus `Hooks` to observe the
  framework's native model and tool events; do not add a second event taxonomy
  unless an AssistantMD API event has no Pydantic equivalent.

Initial deterministic results with Pydantic AI 2.19.0:

- An `httpx.ReadError` before the first streamed model event reaches
  `on_node_run_error`, then `on_run_error`, and bypasses
  `on_model_request_error`.
- An `httpx.ReadError` after partial text emits native stream progress and
  reaches the node- and run-error hooks while bypassing
  `on_model_request_error`.
- A completed tool call exposes its Pydantic `tool_call_id` to before/after tool
  hooks and emits `FunctionToolResultEvent`. If the next model stream then
  disconnects, the failure reaches the node- and run-error hooks but bypasses
  the model-request error hook.
- More precisely, both mid-stream failures reach `on_node_run_error` before
  `on_run_error`. The node-error hook exposes Pydantic-native failure history.
  After partial text it contains the user `ModelRequest` and a `ModelResponse`
  containing that partial `TextPart`. After a completed tool it contains the
  user request, the `ModelResponse` with
  `ToolCallPart(tool_call_id="call-1")`, the matching `ModelRequest` with
  `ToolReturnPart`, and the partial following `ModelResponse`. The settled tool
  result is therefore retained without requiring tool re-execution, but the
  partial response must be handled deliberately when choosing a continuation
  prompt or snapshot.
- The run-level error hook reported an empty message list in the same
  cases. Recovery code must not infer that `on_run_error` supplies a usable
  checkpoint merely because `RunContext` declares a `messages` field.
- AssistantMD's current classifier consistently labels all three synthetic read
  failures `transient_network` and `retryable=true`.
- The production delegate collection helper propagates the same mid-stream
  `ReadError` after Pydantic emits partial progress; it does not retain a result
  or complete message history for the interrupted child run.
- The production task-owned primary chat boundary retains the partial text only
  in its process-local event stream, publishes one terminal `error` event with
  `transient_network` metadata, marks the execution task `failed`, persists the
  accepted user message without partial assistant text, and writes a durable
  unfinished-turn marker containing `error_type=ReadError`.
- Pydantic provider adapters commonly normalize request/opening failures to
  `ModelAPIError` or `ModelHTTPError`, while some failures during iteration can
  still surface from the underlying provider SDK. AssistantMD now classifies a
  connection-specific `ModelAPIError` as `transient_network` and retryable,
  while leaving unrelated generic `ModelAPIError` cases unclassified.
- At the actual `DelegateTool` boundary, a recognized `httpx.ReadError` is
  contained as a failed, retryable tool result so the parent can react. Because
  collection never returns, its child-run audit is empty even when partial text
  was received. The equivalent normalized connection `ModelAPIError` is now
  also contained with `transient_network` metadata instead of aborting the
  parent run.
- Pydantic provider adapters use `UnexpectedModelBehavior` when a stream ends
  without content or tool calls. AssistantMD now classifies that exact
  incomplete-stream signal as `transient_provider` and retryable while leaving
  other `UnexpectedModelBehavior` cases unchanged; malformed provider output
  is not automatically safe to retry merely because it shares the exception
  class.

The repeatable probe lives at
`validation/scenarios/experiments/pydantic_stream_disconnect_probe.py`. It is
an investigation artifact, not yet the stable regression contract.

### Phase 1B: Framework upgrade feasibility

- Upgrade target evaluated on 2026-08-18: `pydantic-ai==2.19.0` and
  `pydantic-ai-harness[code-mode]==0.13.0`, the adopted published releases.
  Resolution succeeds in an isolated environment after adding the explicit
  Pydantic `mistral` extra and moving Monty to a Harness-compatible version.
- Treat this as a framework migration, not a patch bump. Harness documents that
  its 0.x minor releases may break APIs, and the repository is moving from
  Harness 0.1 to 0.11 and Pydantic AI 1.x to 2.x.
- Native `SubAgents` and `StepPersistence` are present in that resolved
  environment. `StepPersistence` supplies settled Pydantic-message snapshots,
  an unresolved tool-effect ledger, run lineage, `continue_run`, `fork_run`,
  and in-memory, file, and SQLite stores. This directly covers the persistence
  substrate that AssistantMD should otherwise have had to invent.
- Deterministic parity probing found one material `StepPersistence` gap. A
  disconnect during the first model stream, after partial text but before the
  model node completes, writes run events but no continuation snapshot. The
  capability's run-error path reads a history reference stashed at completed
  node boundaries, which is still stale at that point. Pydantic's
  `on_node_run_error` does expose the live partial history, so adoption requires
  a thin AssistantMD capability or an upstream fix that saves that live
  frontier.
- The same probe confirmed useful parity elsewhere: after a settled tool cycle,
  the failure snapshot retains the matching native tool call and return plus
  partial following text; SQLite round-trips it; and cancellation during an
  executing tool leaves a `started` unresolved effect record. Harness therefore
  remains a suitable base ledger/store, but not the sole recovery capability in
  its current release.
- `SubAgents` supplies child usage forwarding, per-delegate usage limits,
  timeouts, call budgets, event forwarding, tool inheritance/shared
  capabilities, and bounded error containment. Its native contract is named
  delegates exposed through `delegate_task(agent_name, task)`, rather than
  AssistantMD's current per-call `delegate(prompt, model, tools, ...)` contract.
- Evaluate refactoring delegation toward native `SubAgents`, even if this would
  change the current delegate tool shape. Adoption requires demonstrated parity
  for AssistantMD-specific vault tool binding, principal/context propagation,
  audit evidence, model-selection policy, failure semantics, and validation
  observability. Framework provenance alone is not sufficient reason to replace
  a working bespoke capability.
- The upgrade has confirmed migration work outside delegation:
  - `pydantic-ai[mistral]` (or an equivalent explicit provider dependency) is
    required because the umbrella package no longer installs Mistral support.
  - `OpenAIModel` was replaced by `OpenAIChatModel`; Grok's former provider
    module is absent and must migrate to the current XAI/OpenAI-compatible
    provider contract.
  - Harness requires `pydantic-monty>=0.0.19`; `run_monty_async` is absent
    there, so the authoring runtime must migrate to `AsyncMonty` pool/session
    execution (`checkout` plus `feed_run`) and retain its dataclass, type-check,
    external-function, print, and error contracts.
- Compare native `SubAgents` against `DelegateTool` requirements: dynamic model
  selection, per-call tool binding, thinking settings, audit metadata, usage
  limits, timeout semantics, and model-visible failure behavior.
- Compare `StepPersistence` stores and tool-effect records against AssistantMD's
  SQLite ownership, execution-task, vault-mutation, and principal contracts.
- Assess each Harness capability independently before adoption. Record its
  contract, AssistantMD's current contract, parity gaps, migration cost,
  operational maturity, and validation evidence. Adopt or adapt it only when it
  meets the product's feature and safety needs; otherwise retain the bespoke
  implementation while keeping the dependency current. Architectural
  compatibility with the old `DelegateTool` is not, by itself, a reason to
  reject `SubAgents`, but neither is inclusion in the Harness matrix a reason to
  accept it.

### Harness capability parity gate

The dependency upgrade and capability migrations are separate decisions. The
upgrade may proceed to obtain current Pydantic and Monty behavior without
requiring AssistantMD to replace bespoke features with Harness equivalents.

Before adopting a Harness capability:

1. Inventory the complete AssistantMD contract, including behavior encoded in
   validation scenarios, metadata, logs, persistence, UI/API surfaces, and
   failure handling.
2. Exercise the Harness capability with focused probes rather than relying only
   on its feature-matrix label or README-level description.
3. Compare functional parity, extension points, storage ownership, security
   boundaries, concurrency behavior, failure recovery, and API stability.
4. Choose one of: adopt directly, wrap with a thin AssistantMD adapter, retain
   the bespoke capability, or defer pending upstream maturity.
5. Define validation-first migration scenarios and a rollback boundary before
   changing production behavior.

The initial parity inventory must include at least:

- chat-history compaction versus Harness `compaction`, because AssistantMD has
  established sequencing, reasoning/tool-history integrity, token-budget, and
  persistence contracts;
- `DelegateTool` versus Harness `SubAgents`;
- the proposed recovery design versus Harness `StepPersistence`;
- AssistantMD context assembly versus Harness `context`;
- the authoring/code-execution surfaces versus Harness `code_mode`, planning,
  filesystem, and dynamic-workflow capabilities where their scopes overlap.

This inventory is a discovery exercise, not a presumption that every overlap
should be migrated.

### Phase 2: Safe child sampling retries

- Initial slice implemented: a delegate with no child tools retries a
  classified transient stream failure using global user settings. The default
  is one retry after the initial attempt; `model_stream_retries=0` disables
  automatic replay, and the retry count is bounded from zero to five. Base and
  maximum delays are independently configurable, bounded, and validated so the
  base cannot exceed the maximum. The outer `asyncio.wait_for` remains the total
  deadline, and one shared Pydantic `RunUsage` preserves the request/token
  budget across attempts.
- Tool-enabled delegates currently do not enter that retry loop. They fail
  closed after the first interrupted run until the native effect ledger plus
  live node-error snapshot adapter can prove the recovery frontier is settled.
- `delegate_retry_scheduled` records attempt, next attempt, maximum attempts,
  delay, failure kind, error type, model, workflow/session identity, and the
  `no_child_tools` replay scope.
- The settings do not relax replay safety: enabling retries cannot make a
  tool-enabled run replay automatically.
- Primary chat now uses the same settings for tool-free turns. Attempts share
  Pydantic `RunUsage`; transient classified failures emit
  `chat_retry_scheduled`, reset provisional text/reasoning in the client, and
  replay the original prompt and history. The event is stored in the task event
  buffer, so an SSE reconnect observes the same reset before replacement
  deltas. Exhaustion retains the existing failure marker and manual retry path.
- Primary turns configured with tools and tool-enabled delegates remain
  fail-closed until effect-aware recovery is implemented, even if no tool event
  was observed before the disconnect. This conservative gate avoids treating
  missing stream events as proof that the provider did not initiate a tool call.
- If the upgrade spike cannot supply compatible native persistence/recovery,
  add only the missing thin AssistantMD-owned bounded policy around a Pydantic
  agent run rather than relying only on the HTTP transport.
- Retry automatically when no child side effect has occurred.
- Represent progress with Pydantic `ModelMessage` history and correlate tool
  effects with Pydantic `tool_call_id`; do not invent alternate message or call
  schemas.
- For read-only child tools, permit replay only when completed Pydantic call
  identities and outcomes can be carried forward without re-execution.
- Capture the provider-valid recovery frontier at `on_node_run_error` (or an
  equivalent current-version native persistence hook), then resume by passing
  those same `ModelMessage` objects as `message_history`. Do not serialize a
  second application-owned conversation format merely to retry in process.
- For mutating or unknown tools, fail closed after a post-tool disconnect and
  return an actionable checkpoint/recovery result to the parent.
- Honor provider retry advice when available, otherwise use capped exponential
  backoff with jitter.
- Keep the delegate's overall timeout as a total deadline across attempts, not
  a fresh timeout per attempt.
- Keep Pydantic `UsageLimits` and accumulated `RunUsage` authoritative across
  attempts so recovery cannot silently reset model/tool budgets.

### Phase 3: Client observation hardening

- Retry failed task-event `fetch()` and `reader.read()` operations with bounded
  backoff while the execution task remains queued or running.
- Resume with the last applied sequence and de-duplicate events by sequence.
- On expired event buffers, reload task state and canonical session history
  instead of presenting a generic stream failure.
- Surface reconnecting status separately from terminal model failure.

### Phase 4: Restart durability decision

- Decide explicitly whether active chat/delegate work must survive an
  AssistantMD process restart.
- If yes, write a separate ADR and design persisted run/attempt state, leases,
  idempotent tool execution, and recovery ownership. Do not stretch the current
  process-local coordinator into an implicit durable queue.

## Affected Areas

- `core/tools/delegate.py`: child-run orchestration and failure shaping.
- `core/llm/agents.py`: streamed collection boundary.
- `core/llm/model_factory.py`: request retry policy and provider transport.
- `core/chat/task_execution.py`: parent task event/error reporting.
- `core/chat/task_events.py` and `api/endpoints.py`: replay semantics.
- `static/app.js`: subscriber reconnect and history fallback.
- Settings and documentation if retry budgets/backoff become user-configurable.
- Persistent runtime state only if Phase 4 is approved.

Contract-sensitive surfaces include tool result metadata, validation event
names, SSE payload sequences, execution task state, provider settings, and the
rule that a tool side effect must not be duplicated.

## Validation Target

Maintainers should run the full validation harness. The implementation effort
should extend targeted scenarios first:

- Extend `validation/scenarios/integration/core/delegate_tool.py` with a child
  stream that disconnects before output, after text, and after a tool result.
- Extend
  `validation/scenarios/integration/core/chat_task_event_stream_api.py` with a
  subscriber transport failure and cursor-based recovery assertion.
- Assert one terminal parent result, no duplicate child tool mutation, bounded
  attempt counts, reconnect lifecycle evidence, and preserved session history.
- Add a targeted browser smoke check for reconnect status and canonical-history
  reload after event-buffer expiry.

## Recommended Next Phase

Complete the remaining Phase 1B contract inventory and Harness parity gates,
then turn the result into a staged dependency and capability-migration
validation plan before Feature Development. Upgrading Pydantic AI, Harness, and
Monty does not predetermine adoption of `StepPersistence`, `SubAgents`, or any
other matrix capability. Automatic replay must still be limited to settled
snapshots with no unresolved tool effects; persistence records risk but do not
make external side effects idempotent.
