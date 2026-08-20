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

## Tool Progress Visibility Investigation

### Current observable contract

- Primary chat receives `FunctionToolCallEvent` before each tool executes and
  `FunctionToolResultEvent` when that tool finishes. Parallel tools therefore
  already have independently correlated start/finish boundaries through
  `tool_call_id`.
- AssistantMD publishes those boundaries as buffered `tool_call_started` and
  `tool_call_finished` task events. The browser keeps one entry per call and
  exposes its state with an icon, elapsed time, and aggregate per-state counts.
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
result. The tool-list summary shows per-state counts, active calls show elapsed
time, and an open modal updates its status, elapsed time, events, and final
result as existing events arrive. Persisted unmatched starts are also shown as
interrupted rather than completed.

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
2. **State icons plus elapsed time/counts (recommended first slice):** materially
   better visibility using current events, with only frontend timer lifecycle
   complexity.
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

## Objective

Recover a long-running chat or delegate run from its latest settled Pydantic AI
model/tool boundary after a retryable provider-stream failure. Completed tool
work must remain completed and visible to the model. Whole-task rollback and
replay remains a fallback, not the normal recovery path.

The design must retain AssistantMD's portable canonical chat history. Exact,
provider-bound state needed for recovery is staged separately and is committed
to canonical history only when the logical turn completes.

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
