# Active Run Recovery Implementation Plan

## Status

Phase A in-process recovery is complete through Slice 3 and its targeted
validation passes. This document remains the implementation baseline. It is
intentionally separate from `LONG_RUNNING_TASK_RESILIENCE_PLAN.md`, which
remains the broader program record.

Durable restart recovery and schema work are explicitly deferred. They must not
begin until the Harness lifecycle gates in this plan are resolved and an
observed operational need justifies the additional durable state.

The post-implementation hardening pass is complete for the recovery and browser
reconnection lifecycles. Replacement-task creation is now isolated from
best-effort redirect publication so a notification failure cannot misclassify
a live replacement as abandoned. Browser reattachment cleanup is owned by the
active stream controller, which remains stable when a rollback restart changes
the task ID. Tool recovery metadata now has one fail-closed encoder/decoder,
and `code_execution` is classified as `unknown` because its effects are not
limited to tracked vault mutations. Primary chat and delegate retries share one
bounded budget/backoff policy while retaining their distinct replay-safety
decisions. The browser uses one parsed-event transition and one owner-aware
stream cleanup operation across send, retry, deferred review, and reattachment
flows.

The focused contract review also closes four failure-boundary gaps:

- canonical assistant messages, failure-marker clearing, and deferred-review
  creation commit in one chat-database transaction;
- unresolved `unknown` or manual effects dominate mixed recovery decisions and
  cannot be overridden by a simultaneous vault-transactional effect;
- session active-task lookup prefers the task that is currently running, then
  the oldest queued task, so reload and cancellation follow execution order;
- recovery lifecycle logs carry stable status, task, session, vault, decision,
  replacement, and failure fields, while degraded browser polling fails
  explicitly when task completion cannot be confirmed.

Dependency review found production recovery uses the public Harness
`StepPersistence` and store methods only. A separate compatibility refresh
should evaluate Pydantic AI 2.27.1 and Harness 0.18.1 (the newest stable
releases older than one week at review time) against the existing parity probes
before changing pins. Monty 0.0.21 is current. This refresh is deliberately not
part of the recovery hardening diff.

## Architecture Documentation Audit

### Scope

Audit every file under `docs/architecture/` against the complete branch delta
from `origin/main`, both root implementation plans, ADR 0032, and the current
production code. The review covers chat task ownership and reconnect behavior,
active-run recovery and rollback redirects, tool lifecycle event/detail
contracts, delegate limits and failure handoffs, settings, API/UI surfaces,
runtime ownership, validation artifacts, and explicitly unchanged subsystems.

### Contract-sensitive checks

- Architecture indexes and subsystem ownership links identify the active-run
  recovery and delegate reliability boundaries.
- Chat/session, execution-task, API/UI, runtime, LLM/tool, settings, and
  validation documents agree on lifecycle states, persistence boundaries,
  reconnect semantics, cancellation, rollback, and process-restart limits.
- Documentation describes only the current contract and does not retain
  superseded implementation proposals from the planning files.
- Unaffected architecture documents are checked for claims invalidated by the
  Pydantic AI/Monty upgrades or shared tool-binding changes.

### Validation and next phase

Use a branch-to-document coverage matrix, targeted source inspection, internal
link/path checks, `git diff --check`, and the documentation-relevant portion of
the production static gate. The next phase is documentation implementation,
followed by a cleanup/hardening pass over the complete architecture set.

### Completed coverage

The audit is complete for every page in `docs/architecture/`.

- Updated: `README.md`, `api-ui.md`, `authoring-engine.md`,
  `chat-sessions.md`, `execution-tasks.md`, `llm-tools.md`, `runtime.md`,
  `settings-secrets.md`, `validation.md`, and `vault-state.md`.
- Reviewed with no branch-driven contract change required: `goals.md`,
  `ingestion-pipeline.md`, `multimodal.md`, `scheduler.md`, and
  `session-summaries.md`.

The changed pages now align on process-local recovery ownership, bounded
checkpoint and event retention, sequence reconnect and redirect behavior,
tool-detail persistence/UI state, delegate circuit breakers and failure
handoffs, shared usage limits, and rollback-before-replacement ordering. The
unchanged pages retain accurate ownership and persistence boundaries after the
Pydantic AI and Monty dependency refresh.

### Pre-merge ADR review

One additional durable decision merits an ADR before merge: delegate child-run
containment and failure handoff. The decision spans model instruction layering,
four independent runtime guards, shared structured result classification,
bounded partial-progress salvage, cancellation ownership, and the explicit
choice not to replay or durably checkpoint child tools. ADR 0033 records this
decision with the current implementation and `integration/core/delegate_tool`
as evidence.

No separate ADR is needed for tool progress rendering or full-detail copy;
those are UI/API expressions of persisted tool lifecycle data. Sequence-based
SSE reconnect and canonical-history fallback belong to the existing canonical
task-owned chat decision in ADR 0020. Rollback redirects, effect policy, and
bounded live checkpoints are already covered by ADR 0032.

### Release-notes review

The v0.7.3 entry has been reconciled with the complete branch and simplified
around user-visible outcomes. It covers interruption recovery and its
process-restart boundary, browser reconnect/session reattachment, live and
persisted tool-call visibility, full detail copy, structured failure status,
delegate guardrails and partial handoffs, runtime dependency updates, and the
absence of a database migration. Internal checkpoint, event-buffer, and
instruction-layering mechanics remain in architecture documentation rather than
the user-facing release summary.

## Tool Progress Visibility Investigation

### Current observable contract

- Primary chat receives `FunctionToolCallEvent` before each tool executes and
  `FunctionToolResultEvent` when that tool finishes. Parallel tools therefore
  already have independently correlated start/finish boundaries through
  `tool_call_id`.
- AssistantMD publishes those boundaries as buffered `tool_call_started` and
  `tool_call_finished` task events. The browser keeps one entry per call and
  exposes its state with a compact icon.
- The tool modal can open while a call is running and show its current status,
  elapsed time, arguments, and start event. Existing finish events refresh an
  open modal with the final result.
- Pydantic AI does not provide a generic incremental function-tool result
  stream between those two events. A Python tool returns one final value.
- `delegate` internally consumes the child agent stream and returns only the
  completed output plus audit metadata. Child model/tool lifecycle events are
  not forwarded to the parent chat task.
- `code_execution` captures Monty `print()` callbacks, but returns the captured
  lines only with the final result. They are not currently routed to the chat
  event buffer while execution is active.

### Recommended delivery stages

#### Stage 1: explicit per-call state from existing events (implemented)

Every tool row now has an animated spinner while running, a check mark when
completed, and a warning state when the enclosing chat ends without a matching
result. The collapsed tool list intentionally omits redundant state text and
elapsed time; an open modal shows and updates status, elapsed time, events, and
the final result as existing events arrive. Persisted unmatched starts are also
shown as interrupted rather than completed.

This stage requires no new backend payload, persistence, settings, or provider
contract.

#### Stage 2: bounded structured progress events

Introduce an opt-in `tool_call_progress` task event correlated by
`tool_call_id`. Its stable payload should contain only:

- `tool_call_id` and `tool_name`;
- a bounded phase/status label;
- optional numeric completed/total units;
- an optional short, sanitized message;
- a per-call progress sequence and timestamp.

Progress is transient UI/task state, not canonical model history or a partial
tool return. The event buffer should coalesce or rate-limit updates so verbose
tools cannot evict answer/tool-boundary events. Reload after buffer expiry may
show only `running` until the next progress or finish event.

Initial producers should be `delegate` and `code_execution` only. Delegate can
translate selected child run/model/tool boundaries into parent-safe summaries;
it must not expose child prompts, reasoning, raw arguments, or raw results.
Code execution can translate explicit lifecycle phases and optionally bounded
print previews; arbitrary print output must be treated as potentially
sensitive and untrusted.

#### Stage 3: optional live detail panes for supported tools

For tools with a deliberate streaming contract, the open modal may append a
bounded transient progress log. This is not a generic tool-result stream and
must not change the final `FunctionToolResultEvent`, caching, canonical history,
or recovery semantics. Keep a fixed byte/line ceiling, label truncation, and
render content as text rather than HTML.

### Options and tradeoffs

1. **State icons only:** smallest and safest; immediately answers which parallel
   calls are still running, but gives no internal progress for one long call.
2. **State icons with modal-only elapsed time (implemented):** keeps the list
   scannable while retaining timing detail on demand, using current events with
   only frontend timer lifecycle complexity.
3. **Structured delegate/code progress:** best operational visibility without
   leaking raw output, but requires a new event contract and explicit
   cancellation/reconnect/rate-limit behavior.
4. **Raw live output streaming:** not recommended as a general contract. It is
   unavailable for ordinary tools, risks sensitive/noisy output, complicates
   replay and retention, and can imply that provisional output is canonical.

### Validation target and next phase

Extend `chat_stream_auto_retry` or add a focused parallel-tool scenario that
asserts independently ordered start/finish events and unmatched-call terminal
handling. Add a small frontend harness/smoke test for running, completed,
failed/interrupted, modal-open-during-update, and timer cleanup states. For
Stage 2, assert bounded/coalesced `tool_call_progress` payloads and verify they
never enter canonical chat history or persisted tool results.

Exercise Stage 1 in the production workload before deciding whether the added
complexity and data-exposure surface of Stage 2 is warranted.

## Tool Modal Full-Detail Follow-up (implemented)

### Finding

The modal is not primarily truncating content through CSS. Except for
`code_execution`, active task events carry only the normalized argument and
result previews (200 and 240 characters). The modal and its copy button both
receive that already-truncated value, so copying the rendered block cannot
recover the omitted content. Normal-sized full arguments/results are already
persisted in `chat_tool_events`; oversized results are deliberately represented
by an output-cache reference.

### Implemented behavior

The modal remains compact by default while making full detail available on demand:

- render a useful bounded preview with an explicit `Show all` control when the
  value is longer than the display threshold;
- make Copy operate on the full serialized section value, independent of the
  visible DOM or its collapsed state;
- load full detail through a narrowly authorized session/tool-call detail API
  when the modal opens, rather than adding large values to every replayable task
  event;
- show loading and unavailable states honestly, and label values that are
  themselves tool-produced/cache notices rather than implying the UI clipped
  them;
- when an oversized result has an `artifact_ref`, offer the existing artifact
  access path rather than duplicating the cached payload into chat events.

The existing `<pre>` maximum height and scrolling can remain as a safety net
after expansion. Copy should close over the canonical full value supplied to
the section renderer, not call `getCopyableText()` on a preview DOM node.

### Affected surfaces and validation

- A session-owned tool-detail read boundary in the chat-session API/service and
  store is keyed by session and tool-call ID.
- The modal renderer fetches persisted detail on demand, caches it for the
  entry, renders preview/expanded states, and copies the full formatted value.
- Preserve the current task-event and persistence contracts; this is a read/UI
  enhancement and must not enlarge stream buffers or canonical model history.
- The chat-session persistence scenario covers ownership, missing calls, full
  results, and ordered call/result events. Frontend syntax and review cover the
  preview, expand/collapse, full-value copy, loading/failure, and live-result
  refresh paths until a purpose-built DOM harness exists.

Do not add generic full-result streaming as a follow-up without separately
evaluating its buffer, retention, and data-exposure costs.

## Structured Tool Failure and Delegate Exhaustion Investigation

### Finding: execution completion and domain success are conflated

The delegate limit return is already machine-readable. `delegate` returns a
`ToolReturn` whose metadata contains `status: failed`, `failure_kind:
execution_limit`, `retryable: false`, the controlling limit, and a suggested
action. Similar structured failure envelopes are returned by web capabilities,
`goal_ops`, `workflow_run`, and `content_import`; file read/write failures use
the older but compatible `status: error` convention.

Pydantic reports these as completed function-tool result events because the
Python function returned normally. The chat event publisher currently emits
only the rendered result preview and records every such event as `completed` in
active tool state. It does not propagate `ToolReturnPart.metadata` or
`ToolReturnPart.outcome`. Persisted tool events retain result metadata, but the
rehydration path also marks every result event completed. The UI therefore
cannot distinguish transport completion from a failed domain outcome without
fragile text matching.

### Implemented first correction: one structured terminal-state classifier

- `tool_call_finished` remains the lifecycle event: the invocation did finish.
- The finish payload includes bounded `outcome`, `terminal_state`, and normalized
  failure metadata.
- UI state is derived through one helper shared by live and persisted hydration:
  `failed` for Pydantic failed/denied/interrupted outcomes or metadata status
  `failed`, `failure`, or `error`; otherwise `completed`.
- A distinct failure icon/color and modal section show `failure_kind`, retryability,
  phase, limit, and suggested action in the modal. Do not infer failure from
  prose except as a deliberately bounded legacy fallback.
- The model-visible return remains unchanged so the parent can respond to the
  failure without aborting the enclosing chat turn.

Validation should extend `structured_tool_failure`, `delegate_tool`, and the
persisted session contract to assert identical live/reloaded terminal states.

### Delegate exhaustion and expensive-repeat gap

Delegate runs with child tools do not receive infrastructure retries. The
parent model may issue a new delegate call, but that is a fresh decision. On a
usage-limit or timeout failure, `_failed_delegate_return` currently attaches an
empty audit even though the child may have completed many tool calls. This
contradicts the documented bounded-failure audit contract and leaves the parent
without enough information to scope continuation away from completed work.

The child transcript is not canonical chat history and child calls do not have
a durable continuation record. Vault mutations and explicitly saved artifacts
survive, but read/research progress and the child's synthesis do not. Raising
the limit or automatically rerunning the same prompt would only increase cost
and duplication risk.

### Resilience options, ordered by value

1. **Capture settled failure audit and run a tool-free salvage pass.** Preserve
   messages/audit collected before the limit, select the last provider-valid
   settled boundary, and give a no-tools child pass one chance to summarize
   completed work, artifacts, evidence, and remaining scope. Return `status:
   partial` with the summary plus structured limit metadata. This spends one
   model request but does not repeat child tools and gives the parent a usable
   continuation boundary.
2. **Add per-call budget and deliverable contracts.** Allow a delegate call to
   request a lower tool budget capped by the global setting, require a compact
   deliverable/artifact expectation, and include budget usage in its result.
   This limits blast radius and makes parallel bounded delegates easier to
   compose, but does not by itself salvage an exhausted run.
3. **Add task-scoped delegate checkpoints.** Reuse the branch's settled-boundary
   machinery for child runs so transient provider failures and bounded
   finalization can resume without replaying settled calls while the process is
   alive. Never continue past the configured tool budget with tools enabled.
4. **Add durable work-unit checkpoints only if production evidence demands
   restart recovery.** Persist explicit delegate work-unit identity, completed
   scope/fingerprints, artifact refs, and a single-consumer continuation claim.
   Integrate with `goal_ops` rather than storing provider-native child history
   as canonical chat. This is the strongest option and the largest contract.

Recommended delivery is the structured UI classification first, followed by
settled-audit capture plus a tool-free salvage summary. Evaluate task-scoped
delegate checkpoints only after those two changes are exercised under the
production stress workload.

### Delegate guard and instruction audit

There are three independent child-run guards, not two:

- `delegate_tool_calls_limit` (default 32) bounds child tool invocations;
- `delegate_timeout_seconds` (default 120 seconds) bounds wall-clock duration;
- `delegate_model_requests_limit` (default 75) bounds child model requests,
  including tool-free loops and repeated tool cycles.

Each accepts `0` as disabled. A user who disables timeout and tool calls still
has the request ceiling unless they also disable the request limit. Disabling
all three leaves no delegate-level runaway bound.

AssistantMD does not currently fingerprint or reject semantically identical
model-chosen calls. Pydantic's agent `retries=3` covers tool validation/model
retry behavior; it is not a duplicate-call circuit breaker. Tool-call IDs are
checked for provider-history validity, recovery avoids replaying settled calls
after an infrastructure failure, and individual tools may be idempotent or
deduplicate their own resources. None of those prevents a live child model from
issuing the same tool name and canonical arguments again with a new call ID.

The parent receives strong general guidance in `REGULAR_CHAT_INSTRUCTIONS`: on
a tool error it must read the tool documentation before one corrected retry,
must not rerun cache-producing tools, should scope broad delegations, and should
checkpoint long work. The delegate documentation states the default child
limits and tells the parent to split broad work. The concise `delegate` tool
definition itself does not expose configured limits, so the parent knows exact
values only if it reads settings or after a limit failure returns its structured
metadata.

The child inherits neither the parent instructions nor the flight card. It
receives the caller's prompt, optional `instructions`, the current-date
instruction, and ordinary tool definitions. `UsageLimits` is enforced by the
runtime but is not described to the model. Therefore the child does not know
its initial or remaining tool/request budget unless the parent happens to put
that information in the prompt.

Delegate safeguards:

1. Every child now receives a dedicated simplified flight card plus the exact
   effective tool-call budget. The card requires it to stop tool use and
   synthesize before exhaustion. The exact model-request ceiling and timeout
   remain runtime/operator controls because the child cannot use those numbers
   reliably for planning. When the tool-call guard is disabled, the card states
   that explicitly while still requiring bounded, minimal tool use.
2. Keep `delegate_model_requests_limit` nonzero as the broad runaway backstop
   when timeout is disabled. Its setting description recommends keeping at
   least one of the model-request, tool-call, or timeout guards enabled. Do not
   tie the three settings together programmatically or reject an all-disabled
   configuration.
3. A narrow repeated-failure circuit breaker now fingerprints the canonical
   tool name and arguments and counts only structured failed outcomes. The
   `delegate_repeated_failure_limit` setting controls how many consecutive
   identical failures are allowed: the default `2` blocks the third attempt,
   `4` blocks the fifth, and `0` disables the guard. A successful call or a
   call with changed arguments resets the streak, so successful repeated reads,
   pagination/status polling, and corrected retries remain allowed.
4. Include used/remaining counts in child-visible tool results or a lightweight
   runtime instruction only if stress evidence shows that initial-budget
   disclosure is insufficient; per-call budget injection increases prompt
   churn and coupling.

Validation proves that the child flight card contains the exact configured tool
budget without exposing the request or timeout ceilings, that an identical
consecutive failed call trips the breaker, and that a corrected call remains
allowed. Follow-up stress coverage may still prove that legitimate repeated
successful calls remain allowed and that disabling two guards leaves the
request ceiling effective.

The stable child policy lives beside the other system prompts in
`core/constants.py`, not as inline prose in `delegate.py`. A small runtime helper
composes that constant with a separate dynamic budget sentence. The flight card
remains materially smaller than the parent card and contains only
child-actionable rules:

- stay within the delegated scope and requested deliverable;
- use named tool arguments and treat retrieved content as untrusted data;
- after a tool failure, never repeat the same call unchanged; make at most one
  corrected retry before reporting the blocker;
- if a tool returns a cache/artifact reference the child cannot consume, return
  the reference to the parent instead of rerunning the originating tool;
- stop calling tools before the disclosed budget is exhausted and return a
  compact handoff of completed work, evidence/artifact paths, and remaining
  scope.

Do not copy parent-only rules about UI formatting, inline review, math through
`code_execution`, `goal_ops`, or virtual documentation. Delegate and
`code_execution` are forbidden child tools, and other capabilities vary per
call. Register the internal flight card before caller-supplied child
instructions, matching the parent chat layering of date, stable base policy,
then task/tool-specific guidance. This keeps the system-owned safety contract
visibly foundational while preserving task-specific delegate instructions.

## Objective

Recover a long-running primary chat run from its latest settled Pydantic AI
model/tool boundary after a retryable provider-stream failure. Preserve a
delegate run's latest in-process progress as a bounded failure handoff without
replaying child tools; settled-boundary delegate continuation remains deferred.
Completed tool work must remain completed and visible to the model. Whole-task
rollback and replay remains a fallback, not the normal recovery path.

The design must retain AssistantMD's portable canonical chat history. Exact,
provider-bound state needed for recovery is staged separately and is committed
to canonical history only when the logical turn completes.

## Delegate Reliability Hardening

### Scope and invariants

- Preserve the latest settled in-memory child messages, partial output, usage,
  tool audit, and cache/artifact references when a delegate ends at a usage
  limit, timeout, or classified runtime failure. Return this as a bounded
  handoff to the parent; do not add durable delegate checkpoints or replay
  child tools.
- Once `delegate_started` is emitted, every exit must produce exactly one
  delegate terminal lifecycle event: `delegate_completed`, `delegate_failed`,
  or `delegate_cancelled`. Cancellation must be logged and immediately
  re-raised so the owning chat/workflow task retains authority over its
  terminal state.
- Model resolution, tool binding, agent construction, and child execution use
  the same structured failure boundary. Invalid configuration must not leave a
  start-only delegate lifecycle.
- One shared structured tool-result classifier owns failed/interrupted/success
  interpretation for chat events, delegate audits, and the repeated-failure
  guard. Text inspection remains an audit-only fallback for legacy unstructured
  tool output.
- The repeated-failure guard protects result-informed consecutive retries. It
  must not serialize parallel child tool calls already admitted, and successful
  repeated calls remain legal.
- Delegate timeouts must cancel and await the child run. Validation must prove
  that a cancellation-aware child tool stops and does not mutate state after
  the delegate returns. Blocking or cancellation-suppressing third-party code
  cannot be made into a hard wall by `asyncio`; timeout documentation and event
  semantics must not claim otherwise.

### Affected areas

- `core/llm/agents.py`: optional process-local run-progress snapshots while
  consuming streamed output.
- `core/tools/delegate.py`: unified lifecycle boundary, partial handoff
  assembly, usage/audit/reference metadata, and cancellation event.
- `core/tools/failures.py`: authoritative structured terminal-state
  classification alongside the shared failure envelope.
- `core/chat/task_execution.py` and
  `core/llm/capabilities/delegate_repeated_failure_guard.py`: consume the shared
  classification contract.
- `validation/scenarios/integration/core/delegate_tool.py`: deterministic
  assertions for partial salvage, initialization failure, cancellation,
  timeout cleanup, result classification, successful repeats, and concurrent
  guard admission.

### Stable validation events

- `delegate_completed`: existing success event.
- `delegate_failed`: existing failure event; add partial message/tool/usage and
  handoff/reference counts without logging full child content.
- `delegate_cancelled`: new event with workflow id, model, configured limits,
  partial message/tool/usage counts, and no raw prompt or tool result content.
- `delegate_repeated_tool_failure_blocked`: existing guard decision event.

### Validation target and implementation order

1. Extend `integration/core/delegate_tool` with deterministic failing
   assertions for the shared classifier and lifecycle terminal events.
2. Add streamed progress snapshots and return bounded partial failure handoffs.
3. Move all post-start initialization under the classified lifecycle boundary
   and add cancellation logging/re-raise behavior.
4. Centralize result classification and make chat status, delegate auditing,
   and the repeated-failure guard consume it.
5. Add cancellation-aware timeout and concurrent/repeated-success guard probes,
   then run the individual delegate scenario and the production static gate.

The next phase is Feature Development, followed by targeted Testing and
Validation and a final Refactor and Hardening review.

### Implemented delegate reliability contract

- Stream collection now snapshots the latest in-process messages, output, and
  shared usage counter. Classified failures return a bounded partial handoff,
  compact audit, usage counts, and discovered cache/artifact references.
- Audits distinguish settled from unsettled child tool calls. Failure handoffs
  warn the parent to inspect durable state before replaying a possible mutation
  whose return was not settled.
- Model resolution, child tool binding, agent construction, and execution now
  share one classified failure boundary. Unknown internal failures become
  explicit non-retryable `delegate_internal` tool results.
- Parent cancellation emits `delegate_cancelled` with bounded counts and then
  re-raises `CancelledError`. Timeout cancellation is awaited before returning
  `delegate_timeout`.
- `classify_tool_result_state` is the shared structured result classifier for
  chat task events, delegate audits, and repeated-failure protection. The
  audit-only legacy text fallback uses specific failure markers and does not
  classify benign text such as “completed without error.”
- Delegate terminal failures use non-deduplicated error lifecycle logging;
  global warning deduplication can no longer suppress later `delegate_failed`
  events in the same process.
- Deterministic validation covers partial salvage, structured initialization
  failure, cooperative timeout cleanup, parent cancellation, benign result
  classification, unresolved-call accounting, successful repeated calls, and
  concurrent identical call admission. The focused delegate scenario passes.

## Current Contracts

### Canonical chat history

- `chat_messages` stores full Pydantic `ModelMessage` objects for completed
  turns.
- Successful non-empty tool returns are already preserved in full. ADR 0017
  explicitly rejects size-only truncation of retained successful tool results.
- Tool calls and returns remain atomic protocol units under ADR 0012 and the
  chat-history broker.
- Provider reasoning parts and provider item IDs are transient by default under
  ADR 0021. This is the primary portability trade-off; AssistantMD does not
  generally discard ordinary successful tool results.
- The active user request is committed when a task starts. The remaining
  `final_result.new_messages()` are committed only after the run completes.

### In-flight audit state

- `chat_tool_events` records tool calls and results incrementally by
  `tool_call_id`.
- The table is an audit and display projection. It is not an exact continuation
  format: multimodal values, structured return objects, provider-native fields,
  and oversized-result substitutions cannot always be reconstructed from it.
- Task event buffers are process-local and provide UI replay, not model-history
  recovery.

### Execution tasks and rollback

- One submitted chat turn is one execution task, regardless of the number of
  model requests and tool calls.
- Failed, cancelled, and timed-out tasks invoke the existing terminal rollback
  observer.
- Recorded vault file mutations, including mutations routed through
  `code_execution`, are restored from task-owned snapshots when rollback is
  enabled and complete.
- Rollback is task-scoped. A retry caught inside a still-running task does not
  cross the terminal boundary and therefore does not invoke it.
- External and unrecorded effects are not made reversible by vault rollback.

### Retry behavior already delivered

- Request-opening retries remain owned by Pydantic AI's retrying HTTP transport.
- Tool-free primary chat and delegate streams use the global bounded retry
  policy with shared `RunUsage`.
- Primary chat emits `chat_retry_scheduled` and resets provisional UI output
  before replacement deltas.
- Exhaustion retains the failure marker and manual retry path.
- These are valid no-effect branches of the future recovery coordinator and
  must not be removed.

## Pydantic AI Harness Assessment

Harness 0.13 `StepPersistence` is the persistence substrate. AssistantMD must not
replace its message, run, snapshot, or tool-effect types with parallel domain
types.

It currently provides:

- `RunRecord` identity and lineage using Pydantic `conversation_id`, per-call
  `run_id`, and graph `step_index`.
- Append-only run, model-request, and tool-call events.
- `ContinuableSnapshot` containing native `list[ModelMessage]` history.
- Complete snapshots at settled `CallToolsNode` boundaries, including the
  matching tool-return request before the next model request starts.
- Interrupted snapshots for unsettled tool work.
- A tool-effect ledger keyed by `(run_id, tool_call_id)` with `started`,
  `completed`, and `failed` states.
- In-memory, file, and SQLite stores; all stores support a native per-run
  snapshot bound, and the SQLite store externalizes large media
  through the Harness media store.
- Continuation through Pydantic's `message_history=` rather than a replacement
  agent protocol.

Known gaps established by the parity probe:

- A disconnect during the first model stream can leave no snapshot because the
  live history reference is not yet available at the error hook.
- `StepPersistence` is not a full graph-state or workspace checkpoint.
- The public `StepStore` protocol has no delete, retention, atomic claim, or
  application recovery-status operation.
- The SQLite store self-creates and performs a narrow internal schema upgrade,
  but that does not provide AssistantMD lifecycle ownership or cleanup.
- Capability state beyond message history is not restored automatically.

Any durable implementation therefore requires a thin AssistantMD coordinator
and one narrow live-history adapter. It does not justify a second message or
tool-effect schema.

## Architectural Decision

Use two history tiers.

### Tier 1: canonical session history

- Existing `chat_messages`, tool-event, and compaction contracts remain the
  long-lived source of truth.
- Only completed logical turns are committed beyond the accepted user request.
- Existing portability and reasoning policies continue to apply.
- Provider switching, transcript export, history retrieval, and compaction read
  this tier.

### Tier 2: active-run recovery state

- Contains exact Pydantic/Harness snapshots and tool-effect records.
- Is bound to the original provider, model, tool configuration, session, vault,
  and execution authority.
- Is not exposed as ordinary session history and is not compacted.
- May retain provider-specific reasoning and response item IDs because it is a
  short-lived exact continuation artifact.
- Is finalized or expired after canonical commit, abandonment, or retention
  cleanup.

This separation avoids weakening ADR 0021 globally. A successful recovery uses
provider-bound state temporarily; a completed turn still enters canonical
history through the existing persistence policy.

## Recovery Identities

- **Session ID:** the user-visible conversation and canonical history owner.
- **Execution task ID:** one submitted chat task and the unit of vault rollback.
- **Harness conversation ID:** use the chat session ID for primary chat. A
  delegate uses its own logical conversation ID and records the parent run ID.
- **Harness run ID:** one Pydantic `Agent.run`/`run_stream_events` invocation.
  Every recovery attempt receives a new run ID.
- **Step index:** the settled graph boundary inside one run.
- **Tool call ID:** the canonical correlation key shared by Pydantic history,
  Harness effects, and AssistantMD tool-event audit rows.

Never reuse a Harness run ID for another attempt. Recovery lineage is expressed
through conversation and parent/recovery metadata.

## Recovery State Machine

Application-visible states:

1. `running`: the current run may create newer settled snapshots.
2. `retryable`: a transient failure occurred and a safe complete snapshot is
   available with no unresolved effects.
3. `retry_wait`: bounded backoff is in progress.
4. `resuming`: a new Pydantic run is starting from the selected snapshot.
5. `committing`: the logical turn completed and canonical history is being
   written.
6. `completed`: canonical commit succeeded; recovery state is no longer active.
7. `rollback_required`: no safe incremental frontier exists, but all uncertain
   effects are eligible for task-level vault rollback.
8. `manual_required`: an effect is external, unknown, rollback is partial, the
   provider/model is incompatible, or the retry budget is exhausted.
9. `abandoned`: cancellation, retention expiry, supersession, or explicit
   terminal cleanup ended recovery.

Only one worker may claim `retryable` state. A process restart must not start two
continuations for the same accepted user request.

## Recovery Decision Matrix

### Complete settled snapshot, no unresolved effects

- Resume from the snapshot with `message_history=`.
- Do not rerun completed searches, reads, writes, or external calls.
- Use the same provider/model and tool contract.
- Share the logical retry and usage budgets across attempts.

### Failure before any recoverable snapshot

- Use the existing no-effect replay path when no tool work began.
- Reset provisional UI output before replacement sampling.
- If tool work may have begun but cannot be proven, continue to the unresolved
  effect rules below.

### Unresolved read-only effect

- It is safe to abandon the interrupted frontier and re-execute the read-only
  call or replay from the previous complete snapshot.
- Extra provider/tool cost is acceptable; correctness takes priority.

### Unresolved vault mutation

- Do not resume incrementally from history that assumes the mutation remains.
- Allow the execution task to fail, invoke existing terminal task rollback, and
  verify `rollback_status=completed`.
- A replacement task may replay the accepted request after successful rollback.
- Partial, disabled, unavailable, or failed rollback becomes `manual_required`.

### Unresolved external or unknown effect

- Fail closed.
- Preserve the failure marker, effect identity, and manual retry option.
- Never infer safety from the absence of a result event after a stream failure.

### Completed external effect in a complete snapshot

- Incremental continuation is safe because the exact call and return are
  already in provider-valid history and are not re-executed.
- Whole-turn replay is not safe unless the tool supplies an idempotency contract.

## Tool Effect Classification

Add an explicit tool effect classification to the existing tool metadata
contract rather than maintaining a retry-only allowlist:

- `read_only`: no durable local or external mutation.
- `vault_mutation`: mutations are expected to flow through vault-state tracking.
- `external_effect`: may modify a remote system or communicate externally.
- `unknown`: default for unclassified and dynamically supplied tools.

Classification influences only unresolved-effect and fallback decisions. A
completed tool exchange in a complete snapshot is continued, not replayed,
regardless of classification.

`code_execution` defaults to `unknown`, not `vault_mutation`: although normal
vault file changes are tracked, arbitrary code can have effects outside the
vault. A future restricted execution profile may make a stronger declaration.

## Persistence and Migration Plan

### Phase A: in-process recovery

- Use Harness `InMemoryStepStore`.
- Add no database migration.
- Prove continuation, retry accounting, UI replacement, canonical commit, and
  safety decisions deterministically.
- This phase improves provider disconnect resilience but does not claim process
  restart recovery.

### Phase B: restart-safe recovery

- Use Harness `SqliteStepStore` in a dedicated
  `system/chat_run_recovery.db`; do not mix its generic `runs`, `events`, and
  `snapshots` tables into `chat_sessions.db`.
- Harness owns serialization of `ModelMessage`, snapshot, event, effect, and
  media records.
- AssistantMD requires a small companion recovery catalog for atomic claim and
  lifecycle fields not exposed by `StepStore`. Prefer placing that catalog in
  the same recovery database so recovery state can be reconciled locally.
- The companion table requires an AssistantMD-managed schema version and
  migration. Minimum fields:
  - logical recovery ID and Harness run ID,
  - session, vault, execution task, owner principal,
  - provider, model alias/model string, tool-contract fingerprint,
  - state and recovery-attempt count,
  - source and replacement task IDs when task restart is used,
  - created, updated, claimed, finalized, and expiry timestamps,
  - claim owner/token for single-consumer recovery,
  - last failure classification and selected snapshot step.
- Do not duplicate serialized messages or tool effects in the companion table.
- Reconcile non-atomic cross-layer writes conservatively: a catalog row without
  a usable Harness snapshot is not recoverable; an unreferenced Harness run is
  cleanup-only.

### Harness lifecycle gate

Before Phase B, resolve deletion and retention through one of:

1. a public Harness `delete_run`/retention API, preferably contributed upstream;
2. a public pluggable store whose lifecycle AssistantMD can own without relying
   on Harness-private table names; or
3. an explicitly reviewed AssistantMD `StepStore` implementation only if the
   first two options are unavailable.

Direct deletion from Harness-private SQLite tables is not an acceptable durable
contract.

## Live-History Adapter

The first-stream parity failure requires a narrow adapter around the Pydantic
node error boundary.

Requirements:

- Capture the live Pydantic `ModelMessage` list, never an AssistantMD message
  translation.
- Save only provider-valid complete frontiers by default.
- Preserve partial text only for observability/UI replacement; partial model
  text is not itself a resumable committed response.
- Defer to Harness snapshots whenever Harness supplies an equal or newer safe
  frontier.
- Pin the adapter to public Pydantic/Harness hooks where possible and keep the
  parity scenario that detects stale-history regressions after dependency
  upgrades.
- Remove the adapter when Harness closes the first-stream capture gap and the
  parity scenario passes without it.

## Recovery Coordinator

Introduce one chat-domain coordinator rather than spreading decisions through
`task_execution.py`:

- Build and attach `StepPersistence` to the Pydantic agent capability list.
- Allocate conversation/run identity and recovery metadata.
- Select the newest safe snapshot after a classified failure.
- Inspect unresolved Harness tool effects and tool effect classifications.
- Enforce retry count, delay, provider/model compatibility, and shared usage.
- Return one decision: `resume_snapshot`, `replay_no_effect`,
  `terminal_rollback_restart`, or `manual_required`.
- Emit stable validation/task events.
- Finalize or abandon recovery state after canonical commit or task terminal.

The existing tool-free retry loops become `replay_no_effect` consumers of this
coordinator. Their current settings and UI behavior remain intact.

## Canonical Commit Rules

- Recovery snapshots never become visible canonical history merely because a
  run failed.
- A successful logical turn commits exactly once through the existing
  chat-store write boundary. For an uninterrupted run, the source remains
  `final_result.new_messages()`. For a resumed run, assemble the logical-turn
  delta from the selected snapshot plus the resumed run's new messages, remove
  history that predates the accepted user request, and then apply
  `_messages_after_accepted_user_request(...)`. Do not persist only the resumed
  tail, which would orphan the completed tool cycles that made recovery useful.
- The accepted user request is never duplicated.
- A recovered result clears the latest-turn failure marker.
- Compaction cannot select active recovery snapshots.
- Session fork, export, and provider switching read canonical history only.
- If canonical commit fails after model completion, do not rerun tools. Mark the
  recovery record `manual_required` and retain the final snapshot for repair.

## Provider Compatibility

Incremental continuation requires the same effective provider and model unless
a provider adapter explicitly proves compatible replay.

Record a compatibility fingerprint containing at least:

- provider name and auth mode,
- resolved model string,
- relevant model capabilities,
- reasoning-persistence mode,
- tool names plus schemas/effect classifications,
- context/compaction history revision used for the run.

A mismatch rejects the checkpoint. Provider switching then uses canonical
portable history and, where safe, whole-task replay.

OpenAI `previous_response_id` may later optimize continuation, but it must remain
an optional provider feature. Native Pydantic messages are the baseline recovery
format so the architecture is not OpenAI-only.

## UI and API Contracts

Retain `chat_retry_scheduled` for same-task recovery. Extend its payload with:

- `strategy`: `replay_no_effect` or `resume_snapshot`,
- source and next Harness run IDs when available,
- selected checkpoint step,
- completed and unresolved tool counts,
- `reset_response`, attempt, maximum attempts, and delay.

Add `chat_retry_redirect` only for terminal rollback/replacement-task recovery.
Minimum payload:

- source and replacement task IDs,
- session ID,
- rollback outcome,
- retry attempt/max attempts,
- failure kind and strategy `terminal_rollback_restart`.

The browser must follow the replacement task while rendering one logical
assistant response. External chat surfaces consume the same normalized task
events and must not require web-specific recovery logic.

Session detail should expose only actionable recovery status, not raw provider
messages or Harness internals.

## Observability Events

- `chat_recovery_checkpoint_selected`: safe snapshot chosen; includes task,
  session, run, step, and settled/unresolved counts.
- `chat_retry_scheduled`: same-task retry scheduled; existing event extended as
  described above.
- `chat_recovery_rejected`: checkpoint or strategy rejected; includes stable
  reason such as `provider_mismatch`, `unresolved_external_effect`,
  `rollback_unavailable`, or `snapshot_missing`.
- `chat_retry_redirect`: replacement task created after completed rollback.
- `chat_recovery_committed`: recovered logical turn committed exactly once.
- `chat_recovery_abandoned`: recovery state finalized without automatic resume.

Do not emit raw tool results, prompts, reasoning, or secrets in these events.

## Validation-First Delivery

### Slice 1: settled read-only continuation, in memory

Add a deterministic integration scenario where:

- a primary chat performs multiple model/tool cycles,
- completed web-like/read-only calls return stable artifacts,
- a later model stream emits provisional text and disconnects,
- Harness exposes a complete snapshot with no unresolved effects,
- recovery starts a new Pydantic run from that snapshot,
- completed tools execute exactly once,
- provisional UI text is reset,
- the final assistant response and tool history commit exactly once,
- shared usage and the global retry budget span both runs.

Implemented on `dev/resilience-enhancements` using a task-scoped Harness
`InMemoryStepStore`; no schema migration is introduced in this slice.

### Slice 2: safety matrix

Add deterministic cases for:

- unresolved read-only call: replay permitted,
- unresolved vault mutation: incremental resume rejected,
- completed external effect in a settled snapshot: continuation permitted
  without re-execution,
- unresolved external/unknown effect: automatic recovery rejected,
- retry budget zero and retry exhaustion,
- cancellation during retry delay.

Foundation implemented: `BaseTool` owns a typed recovery policy with an
`unknown` default; resolved bindings carry it in both `ToolSpec` and Pydantic
tool metadata. Detailed `get_instructions()` payloads have been removed while
the lightweight, description-derived capability summary remains intact.

Coordinator matrix implemented: unresolved replay-safe effects select
`replay_no_effect` from Harness's interrupted snapshot; unresolved vault
effects select `terminal_rollback_restart`; external, manual, and unknown
effects select `manual_required`. Pydantic's repair of interrupted history and
exactly-once pending read-tool execution are pinned by targeted validation.
Rollback/replacement-task execution remains Slice 3.

### Slice 3: vault rollback redirect

Validate that an unresolved vault mutation:

- terminates the source task,
- completes existing rollback before replacement task creation,
- does not duplicate the accepted user request,
- redirects the client to the replacement task,
- produces one final canonical turn,
- remains failed/manual when rollback is partial or disabled.

Implemented in process: the source task reaches terminal failure first, the
existing task rollback observer restores vault state, and a failed-task hook
verifies the rollback outcome before creating a replacement task. The source
event stream terminates with `chat_retry_redirect`, and browser plus validation
consumers follow the replacement while preserving one logical response.
Rollback-disabled and incomplete outcomes fail closed without replacement.

### Slice 4: restart recovery (deferred)

After the Harness lifecycle gate and schema migration:

- stop the runtime after a settled checkpoint,
- restart against the same system root,
- atomically claim one recovery record,
- resume once with the original authority/provider/model contract,
- verify no completed tool re-executes,
- verify stale, incompatible, expired, and already-claimed records fail closed,
- verify cleanup removes catalog, snapshots, effects, events, and externalized
  media without touching canonical session history.

### Existing regression targets

Continue running individual scenarios for:

- tool-free primary and delegate automatic retry,
- manual retry and latest-turn failure markers,
- SSE replay and response reset,
- chat cancellation and code-execution rollback,
- deferred review continuation,
- compaction/tool-history integrity,
- Harness StepPersistence parity.

Maintainers retain ownership of the full validation suite.

## Implementation Slices

1. **Coordinator seam:** introduce recovery decisions and move the existing
   no-effect policy behind it without behavior change.
2. **Harness attachment:** attach `StepPersistence(InMemoryStepStore)` to primary
   chat using Pydantic capability composition and stable run identity.
3. **Settled continuation:** resume a retryable failed run from the newest
   complete snapshot and commit once.
4. **Effect classification:** add tool metadata and unresolved-effect routing.
5. **Rollback redirect:** connect the decision layer to terminal task rollback
   and replacement-task events.
6. **Harness lifecycle resolution (deferred):** add or adopt public deletion,
   retention, and claim support.
7. **Durable catalog/migration:** introduce `chat_run_recovery.db` and startup
   reconciliation.
8. **Restart recovery:** claim and resume eligible records during runtime
   bootstrap/session activation.
9. **Hardening:** retention, redaction, metrics, compatibility fingerprints,
   dependency-upgrade parity, and ADR/architecture documentation.

Slices 1-5 and the in-process portions of Slice 9 are complete. Slices 6-8 are
not part of the current delivery.

The delegate failure-handoff hardening pass additionally bounds traversal of
untrusted nested tool results, tolerates cyclic/non-JSON payloads without
masking the original failure, and resets repeated-structured-failure tracking
when an intervening tool execution raises.

### Slice 5A: subscriber reconnect hardening

Harden the existing process-local task subscription contract without adding
durable recovery state:

- reject replay cursors that precede the retained event window with a stable
  `410 ChatTaskEventCursorExpired` response and sequence details;
- retry transient browser SSE transport failures with a small bounded policy
  while preserving the last acknowledged task-event sequence;
- when a session is loaded and the page does not already own its stream, query
  the active-task endpoint and attach to the running task;
- fall back to persisted session reload after an event gap rather than
  presenting a retained suffix as a complete response.

Validation pins buffer-level cursor expiry and the API error envelope. Frontend
syntax and focused manual contract review cover the browser reconnect path.

Each slice must preserve a working manual-retry fallback and pass its targeted
scenario before the next slice begins.

## Affected Areas

- `core/chat/task_execution.py`: orchestration and task event integration.
- New `core/chat/recovery.py` or package: coordinator and decision policy.
- `core/llm/agents.py` and capability construction: Harness attachment.
- `core/chat/chat_store.py`: canonical commit boundary only; avoid recovery
  storage in this class.
- `core/chat/schema.py`: unchanged through Phase A; companion migration in
  Phase B only.
- `core/chat/deferred_reviews.py`: continuation compatibility and mutual
  exclusion with active recovery.
- `core/tools/base.py`, tool registry/settings metadata: effect classification.
- `core/vault_state/rollback.py`: expose/observe completed rollback outcome for
  redirect, without duplicating rollback implementation.
- `core/runtime/execution_tasks.py` and task runner: terminal chaining and
  replacement-task identity.
- `static/app.js` and chat rendering: checkpoint status and redirect handling.
- `validation/scenarios/integration/core/`: executable recovery contracts.
- `docs/adr/`: new accepted ADR before durable recovery ships.

## Explicit Non-Goals

- Replacing Pydantic `ModelMessage`, tool-call IDs, or `message_history`.
- Making canonical history provider-specific by default.
- Adopting Harness compaction, code mode, or subagents without separate parity
  review.
- Resuming an arbitrary graph node or Python coroutine stack.
- Automatically replaying unresolved external effects.
- Treating vault rollback as proof that every possible tool effect was undone.
- Shipping restart recovery without bounded retention and single-consumer claim.

## Open Decisions Before Durable Implementation

1. Whether Harness will expose public delete/retention primitives in the target
   release or AssistantMD must supply a public-protocol store.
2. Whether atomic recovery claims belong in an upstream Harness store extension
   or the AssistantMD companion catalog.
3. The exact retention duration and whether completed recovery evidence is kept
   briefly for diagnostics or removed immediately after canonical commit.
4. Whether delegate checkpoints share the primary recovery database in the
   first durable release or follow after primary chat stabilizes.
5. Whether a restricted `code_execution` profile can ever declare
   `vault_mutation` rather than `unknown`.

None of these blocks Slice 1 through Slice 3 in memory. They do block a claim of
restart-safe durable recovery.

## Definition of Done

- A late transient disconnect resumes from the latest settled model/tool
  boundary without repeating completed tools.
- Canonical history commits one complete logical turn and remains portable by
  default.
- Unresolved effects follow the explicit safety matrix.
- Vault rollback/replay is a verified fallback, not the default continuation.
- Retry settings, usage limits, cancellation, and UI events apply across all
  recovery attempts.
- In-process recovery state is bounded and discarded with the execution task.
- If restart recovery is later adopted, it is single-consumer,
  migration-backed, retention-bounded, and uses public Harness/Pydantic
  contracts.
- Manual retry remains available whenever automatic recovery is unsafe or
  exhausted.
- The new ADR and current-contract architecture documentation match the shipped
  behavior.
