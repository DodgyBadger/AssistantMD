# Long-Running Tasks Research and Implementation Plan

## Scope

Improve AssistantMD's ability to pursue complex knowledge-work goals that run longer than a typical chat answer but are still bounded by a user's workspace, project, client folder, or vault-maintenance task. Examples include research synthesis, report drafting, source review, project/client folder processing, and batched administrative work across a vault.

The target is not a coding-agent framework that runs autonomously for days. AssistantMD already supports scheduled workflows that can process files in batches over time. This plan focuses on the gap between ordinary question-and-answer chat and existing scheduled/background workflows: a user gives the agent a substantial research or project goal, and the system helps it track progress, manage context, recover from failures, and produce auditable work without losing the user-owned markdown workspace model.

This document is the implementation plan and status record for the long-running task hardening effort.

## Product Philosophy Fit

AssistantMD's long-running task support should preserve the existing design philosophy:

- Full ownership of user files and workflows.
- Maximum flexibility to structure work around user needs.
- A markdown vault as the source of truth for both user and agent.

The default design should treat markdown as the source of meaning and SQLite as a runtime coordination aid. Markdown should own the goal brief, source notes, draft report, progress narrative, decisions, and user-facing handoff. SQLite should only own machine invariants that markdown handles poorly: exact task ids, event ordering, idempotency keys, retry state, token usage, cancellation state, and restart reconciliation.

Default long-running support should be softly opinionated, like memory:

- provide a few durable primitives and helpers;
- ship default markdown conventions and workflows;
- let users decide whether a workspace uses those conventions, replaces them, or handles long work entirely with ordinary workflows and markdown.

The primitive layer should not become a mandatory "goal framework" around every task.

## Goal Authority Model

SQLite should be the source of truth for operational goal state. Markdown should be the default user-editable projection and context material.

Operational state includes:

- `goal_id`,
- status,
- current step,
- step ids,
- task ids,
- event order,
- checkpoint ids,
- timestamps,
- retry/cancellation state,
- usage and budget counters,
- restart reconciliation state.

Markdown owns human-facing meaning:

- objective narrative,
- success criteria,
- project/client context,
- source notes,
- decisions,
- progress summaries,
- draft outputs,
- workspace-specific playbook conventions.

Default composition may scaffold and maintain files such as:

- `goal.md`,
- `progress.md`,
- `sources.md`,
- `draft.md`.

Those files are analogous to `README.md` and `playbook.md`: useful conventions that the default context script can load, but not canonical runtime databases. A user can change the convention by editing context/workflow scripts to look for different files or different structures.

Rules:

- `goal_ops` should not blindly parse arbitrary markdown and treat it as authoritative state.
- `goal_ops(create)` may scaffold default markdown files and link them as artifacts.
- `goal_ops(update)` may update linked markdown projections when the default composition opts into that behavior.
- User edits to markdown are treated as context/instructions, not automatic state mutation.
- If a user wants markdown-driven goal state, they can write a workflow or context script that deliberately reads their files and calls `goal_ops(update)`.
- If SQLite and markdown disagree on operational state, SQLite wins; markdown disagreement should be surfaced as context drift or a warning, not silently synced.

## Research Synthesis

Current SOTA patterns converge on the same few requirements, but AssistantMD should adopt them selectively for knowledge work rather than copying coding-agent orchestration wholesale:

- Durable execution is the core gap for production agents. LangGraph frames persistence as checkpointed thread state plus longer-term stores for recovery, conversation continuity, human-in-the-loop workflows, time travel, and fault tolerance. Temporal's Pydantic AI integration makes the same point more strongly: long-running agents need to survive API failures, exceptions, restarts, deploys, and human approval delays without rerunning completed work. For AssistantMD, this should usually mean a recoverable research/report task or workflow step, not unconstrained multi-day autonomy.
- Long-running work needs explicit external memory, not only compaction. Anthropic's long-running agent harness uses a feature list, progress file, git history, and an initializer/coding-agent split so each new context window can resume from durable artifacts rather than guessing. For AssistantMD, the equivalent is a workspace folder with markdown-owned goal, source notes, progress, draft, and artifact files.
- Subagents are useful when their context can stay isolated. Anthropic's multi-agent research system uses an orchestrator-worker pattern where subagents explore independently and return condensed findings. The main cost/risk tradeoff is large: they report multi-agent research uses far more tokens than chat, so delegation must be reserved for breadth-heavy work where parallel exploration pays off.
- Context engineering should minimize high-signal tokens. Anthropic recommends curated tools, compaction tuned for recall before precision, structured note-taking outside the context window, and subagents that return compact summaries or artifact references.
- Observability must represent the agent process, not just the final answer. OpenAI Agents SDK exposes tracing for LLM generations, tool calls, handoffs, guardrails, and custom events. It also tracks per-run and per-request token usage, including cached and reasoning-token details.
- Agent retries need provider-aware policy, not generic reruns. Pydantic AI documents retry transports that respect `Retry-After`, use exponential backoff, and retry network/timeouts/server failures while avoiding retries for permanent errors.
- Evaluation should focus on outcomes and checkpoints. Anthropic recommends flexible end-state evaluation for multi-agent systems, with discrete checkpoints for persistent-state mutations rather than requiring one exact path.

## Current AssistantMD Strengths

- Chat history is durable in SQLite through `core/chat/chat_store.py`, and completed history can be compacted through durable checkpoints in `chat_compaction_checkpoints`.
- Chat and workflows already register cancellable execution tasks through `core/runtime/execution_tasks.py`.
- Workflows have a shared governor in `core/runtime/workflow_governor.py` with vault-level serialization, global concurrency limits, task metadata, cancellation, and timeout handling.
- `workflow_run` already supports background `start`, `status`, and `cancel`, so the tool surface has a user-visible async pattern.
- Scheduled and manual workflows can already do genuinely long-running vault maintenance, including folder watching, batch processing, pending-file tracking, and periodic processing across large file sets.
- Workspace folders already give knowledge work a natural unit of scope: project, client, report, research dossier, or vault-wide administration.
- `delegate` has useful guardrails: no nested delegate/code execution, tool-call and timeout limits, bounded-failure returns instead of parent crashes for usage/timeouts, and compact child-agent audit metadata.
- Oversized chat tool output is cached, and tool events are persisted structurally in `chat_tool_events`.
- Existing validation scenarios already cover chat cancellation, streaming failure logging, workflow async start/status/cancel, delegate failure modes, compaction, and task rollback.

## Primary Weaknesses

1. Execution task state is process-local.
   `TaskCoordinator` keeps active and recent terminal task records in memory. After restart, users lose task visibility and cannot resume or inspect a running/queued long-running workflow through task APIs. This is acceptable for short work but weak for multi-hour goals.

2. There is no first-class goal/run ledger.
   A chat session can persist messages, and a workflow can run as a task, but there is no durable object that records the goal, plan, step states, artifacts, budget, user checkpoints, subagent children, and latest recovery point.

3. Compaction is chat-history oriented, not goal-oriented.
   Current compaction summarizes older messages plus recent raw messages. It already works well for long-lived sessions when the summary behaves like operational recovery state, but the prompt contract is not explicit enough about goal state: active objective, plan, next action, blockers, artifacts, source refs, failed attempts, and check-in requirements.

4. Automatic compaction policy is under-specified for long-running tasks.
   AssistantMD already supports automatic post-turn compaction through `compaction_type: auto`. The right model is not "auto-compaction is dangerous"; it is "auto-compaction is acceptable when the summary contract is operational enough." Long-running tasks may need automatic context-window management before the goal is complete. Hardening target: make compaction summaries function as recovery cards, define the trigger/audit contract, and decide whether long-running mode should inherit ordinary chat settings or use an explicit per-goal policy.

5. Cost accounting is incomplete for long runs.
   AssistantMD estimates prompt/history tokens and enforces tool-call limits, but it does not appear to persist provider-reported per-request usage, cached tokens, reasoning tokens, per-subagent cost, or goal-level budgets.

6. Network/API resilience is mostly implicit.
   Model instances use a configured timeout, and workflows/delegates have timeouts. There is no centralized provider retry policy with backoff, `Retry-After` handling, retry event logging, or idempotency guidance around tool calls that should not be retried blindly.

7. Subagents are synchronous child calls.
   `delegate` is useful for bounded inference, but it does not create durable child task records, stream progress, return artifact references as a first-class contract, or let the parent continue while children run.

8. Check-ins are procedural rather than system-owned.
   A workflow or agent can ask the user questions, but there is no durable "awaiting user" task status, no resumable approval/check-in payload, and no UI/API affordance for goal checkpoint review.

9. Transparency is split across logs, tasks, tool events, and vault activity.
   Each piece is useful, but long-running goal audit needs one queryable timeline that ties together goal, task, turn, step, workflow, delegate call, tool events, files, usage, retries, and user approvals.

## Existing Brittle Points and Code Smells

These are lower-level risks in the current code that could derail or waste effort during long-running work even before a new goal subsystem exists.

1. Tool-call pairing is too narrow in `retrieve_history(...)`.
   `core/authoring/helpers/history/retrieve.py` only creates an atomic `ToolExchange` when one `ModelResponse` contains exactly one `tool-call` part and the next `ModelRequest` contains exactly one matching `tool-return` part. If a provider emits parallel tool calls, or if a request/response carries multiple parts, the helper falls back to ordinary history messages. That is brittle for context scripts that slice/reorder history and can reintroduce invalid provider history. Hardening target: parse all tool calls/returns in adjacent request/response messages, preserve the full paired batch as one safe unit, and emit a validation warning for orphaned calls/returns.

2. Compaction preserves boundary pairs but not full malformed-history diagnostics.
   `core/chat/compaction.py` shifts the recent-history boundary when a tool call/return pair would be split, which is good. It does not appear to validate the whole effective history for orphaned returns, orphaned calls, duplicate tool ids, or multiple-call batches before summarization. Hardening target: add a shared `validate_tool_history_integrity(...)` helper used by compaction, `retrieve_history`, fork/session-prefix logic, and chat preflight.

3. Streaming chat error handling may leave an accepted user turn without an explicit assistant failure record.
   Streaming persists the accepted user request before model execution, emits an SSE error chunk on failure, logs the failure, and then raises for unexpected exceptions. It does not persist a durable assistant-visible failure message. That keeps failed model output out of history, but a long-running agent resuming from the session may see a user request with no assistant outcome. Hardening target: persist a structured internal failure marker or goal event that context assembly can include as "previous turn failed during phase X" without polluting normal transcript exports.

4. API error responses hide too much detail from non-debug clients.
   `api/utils.py` returns `"An unexpected error occurred"` plus only `error_type` when debug mode is off. That is reasonable for public APIs, but poor for a local single-user agent system where the model may need actionable recovery details. Hardening target: add agent-safe error summaries with stable `error_type`, `phase`, `retryable`, `suggested_action`, and relevant ids while still avoiding secrets/tracebacks.

5. Tool errors often return plain prose strings instead of structured failure metadata.
   Web tools such as `web_search_tavily`, `web_search_duckduckgo`, and `tavily_extract` catch broad exceptions and return strings like `"Tavily API error: ..."`. This avoids crashing the parent run, but it makes transient network failures, rate limits, missing secrets, and true no-result states hard to distinguish. Hardening target: standardize tool failure returns as `ToolReturn(metadata={"status": "failed", "error_type": ..., "retryable": ...})` while keeping concise text for the model.

6. Tool binding errors can fail an entire agent before it can adapt.
   Missing API keys for configured tools are raised during tool construction for some tools. If a user includes a tool in a long-running task and the secret is missing or stale, the chat/workflow can fail at preflight rather than letting the agent choose another tool. Hardening target: distinguish required-tool preflight failures from optional-tool unavailability; expose unavailable tools as structured capability diagnostics where safe.

7. Delegate limits are global and static.
   `delegate_tool_calls_limit` and `delegate_timeout_seconds` are blunt global settings. The current bounded-failure messages are good, but broad research tasks may churn through repeated failed delegate calls if the child scope is only slightly too large. Hardening target: add per-call optional budgets within configured maxima, return partial audit/progress when a child times out, and teach the parent through metadata whether to split, retry later, switch tools, or escalate to workflow/background child.

8. Delegate failure metadata does not preserve partial child work.
   On usage-limit or timeout failures, `delegate` returns an empty audit because the exception path does not have completed child messages. That loses useful evidence about what the child tried before failure. Hardening target: capture incremental child tool events through hooks or a child event sink so partial progress survives bounded failures.

9. `workflow_run(start)` is async, but child/subtask observability is shallow.
   The tool returns a task id and status polling works, but the parent agent does not get step-level progress, heartbeat, partial artifacts, or structured "still waiting because..." reasons. Hardening target: add task heartbeat/progress metadata updates for long workflows and make `workflow_run(status)` return progress plus artifact refs, not only lifecycle status.

10. Background workflow exceptions can be swallowed after task marking.
   `WorkflowGovernor.start_workflow` and system-template workflow startup catch broad exceptions in background task wrappers and return. The coordinator usually marks failures inside `execute_workflow`, but broad swallowing makes it easy for future bugs before/around task tracking to disappear into logs. Hardening target: emit a final background-task wrapper event whenever an exception is swallowed, including task id and whether the task was already terminal.

11. Queue and timeout policy can silently create starvation or runaway work.
   Vault lane locks serialize workflows per vault and `max_concurrent_workflows=0` disables global concurrency. That is flexible, but for long-running goals it means one stuck workflow can block a vault lane indefinitely unless timeout/checkpoint policy is configured. Hardening target: add queued-time metrics, heartbeat timeouts, queue-age warnings, and user-visible "blocked behind task X" messages.

12. Usage and output limits can cause hidden churn.
   `chat_tool_calls_limit=0` disables chat tool-call limits by default; `auto_cache_max_tokens` can replace large tool outputs with cache notices; `max_output_tokens` can truncate model responses provider-side. These settings are useful but the agent has no unified view of why it is failing to make progress. Hardening target: include active limit settings and limit-trigger events in goal/task context, and classify limit-triggered failures as `budget_limited`, `context_limited`, or `tool_limited`.

13. There is no shared retry classification for model/tool/network errors.
   External tools and model calls use timeouts, but retryability is decided ad hoc or not at all. Long-running agents need to know if an error is transient, permanent, auth/configuration-related, or caused by bad input. Hardening target: create a shared `ErrorEnvelope`/`FailureClassification` helper used by tools, API responses, workflow execution, and future goal events.

14. Activity logging is good but not always agent-actionable.
   Many events are logged for validation/activity, but the agent often receives only a plain tool result or generic API error. Hardening target: make critical event ids/task ids/checkpoint ids flow back to the agent so it can inspect status or report accurately.

15. Validation covers important contracts but not adversarial long-run degradation.
   Existing scenarios cover cancellation, rollback, delegate limits, compaction, streaming failures, and workflow async operations. Missing probes include multi-tool-call history batches, orphaned tool returns, transient provider retry, missing optional tool secrets, partial delegate timeout evidence, workflow heartbeat absence, and post-restart interrupted-task reconciliation.

## Risk Register

Ranking uses two dimensions:

- Severity: impact if the risk occurs.
- Likelihood: expected frequency in real AssistantMD usage.

Priority is the practical product of both. A severe but rare risk may rank below a moderate but common source of repeated long-running-task failure.

| Risk | Severity | Likelihood | Priority | Why it matters | Early mitigation |
| --- | --- | --- | --- | --- | --- |
| Process restart loses active task visibility | High | Medium | P0 | Long workflows can outlive the in-memory `TaskCoordinator`; after restart, user and agent lose authoritative state. | Durable goal/task ledger and startup reconciliation. |
| Non-idempotent retry or resume duplicates effects | Critical | Medium | P0 | Retrying file writes, imports, deletes, sends, or external mutations can corrupt user state. | Classify operations by idempotency; checkpoint before non-idempotent work; require explicit resume policy. |
| Tool-call history pairing breaks during context manipulation | High | Medium | P0 | Invalid tool call/return history can derail future model calls or silently omit evidence. | Shared tool-history integrity validator and batch-safe history units. |
| API/tool failures return non-actionable prose | Medium | High | P0 | Agents waste turns parsing strings, retrying permanent errors, or giving poor user explanations. | Structured failure envelope with retryability and suggested action. |
| Silent task stalls | High | Medium | P0 | A goal can appear active while no useful work happens, consuming time or blocking queues. | Heartbeats, stale-progress warnings, and stalled status. |
| Premature goal completion | High | Medium | P1 | Long-running agents often mistake partial progress for done. | Explicit success criteria, checkpoint evidence, and completion validation. |
| Plan drift away from original objective | High | Medium | P1 | The agent may work hard on adjacent tasks while missing the actual goal. | Durable objective, scoped steps, and periodic objective-drift checks. |
| Stale checkpoints or durable memory mislead future work | High | Medium | P1 | A checkpoint can become false after files/settings/sources change. | Include source revisions, file hashes, and freshness checks. |
| Context poisoning from web/retrieved content | Critical | Low-Medium | P1 | Long-running tasks consume more untrusted text and can persist injected instructions. | Preserve untrusted-data boundaries in checkpoints and memories; validate write-capable workflows. |
| Delegate limits cause churn or lost partial progress | Medium | High | P1 | Bounded failures are safe, but repeated failed children waste tokens and obscure useful partial work. | Partial child audits, per-call budgets, and parent guidance metadata. |
| Over-delegation burns tokens or duplicates work | Medium | Medium | P1 | Multi-agent research can be expensive and noisy when decomposition is weak. | Delegate budget heuristics, child scope contracts, and duplicate-work detection. |
| Under-delegation exhausts parent context | Medium | Medium | P1 | Parent agent may serially perform broad work and lose context. | Heuristics for when to delegate or launch background workflows. |
| Cancellation semantics are misunderstood | High | Medium | P1 | Local rollback may not undo external effects, caches, or imported/generated artifacts. | Cancellation result should distinguish rolled-back, retained, and external/unknown effects. |
| Sensitive data persists in checkpoints/audits/logs | Critical | Low | P1 | Long-running audit trails increase chances of accidentally retaining secrets/private text. | Redaction policy, secret scanning for goal artifacts, and provenance labels. |
| Queue starvation behind long workflow | Medium | Medium | P2 | One vault lane can block unrelated work indefinitely. | Queue age metrics, user-visible blocking reason, timeout/priority controls. |
| Artifact/reference decay | Medium | Medium | P2 | Cache refs, paths, URLs, and imported sources may vanish or change before resumed use. | Artifact registry with existence/freshness checks. |
| Compaction drops uncertainty or caveats | Medium | Medium | P2 | Summaries can sound authoritative while losing failed attempts or open questions. | Checkpoint schema with required uncertainty/open-question fields. |
| Check-in fatigue | Medium | Medium | P2 | Too many approvals make long-running mode unusable. | Configurable check-in policy by risk level and budget. |
| Opaque autonomy | Medium | Medium | P2 | Users cannot tell whether the agent is running, blocked, waiting, retrying, or spending. | Goal timeline, active status, progress summaries, budget visibility. |
| Cross-scope context leakage | High | Low | P2 | Subagents/workflows could mix vault/session/workspace context. | Scope fields on all goal/child records and enforced API filters. |
| Tool privilege creep | High | Low | P2 | Long goals combine tools in surprising ways, increasing write/delete risk. | Capability profiles and step-level allowed tools. |
| External-source trust laundering | High | Low | P2 | Bad web content can become trusted durable memory. | Provenance labels and source-quality metadata on notes/checkpoints. |

Initial implementation should focus on P0 risks, then select P1 work only when it supports the same slice. P2 risks should remain visible in docs and validation backlog but should not expand the first implementation phase.

## Recommended Architecture

### 1. Harden Existing Long-Running Surfaces First

Before adding new goal primitives, make the current chat/workflow/tool stack more reliable for bounded knowledge-work runs.

Priority hardening targets:

- Tool-history integrity across retrieval, compaction, context assembly, and session forking.
- Automatic compaction policy, prompt strategy, and audit visibility for long-running tasks.
- Structured tool/API failure metadata with retryability and suggested next action.
- Streaming failure recovery context when a user turn is accepted but no assistant response is persisted.
- Workflow/task heartbeat and progress metadata so "running" is distinguishable from "stalled".
- Error and retry classification shared across model calls, web tools, workflows, and future `goal_ops`.

This is the highest-leverage work because `goal_ops` will only be useful if the lower-level operations it composes already report state and failures clearly.

### 2. Define Automatic Compaction Policy Before `goal_ops`

AssistantMD already has `compaction_type: none|suggested|auto`, `compaction_keep_recent`, and `compaction_token_threshold`. Existing long-lived assistant sessions show that repeated compaction can work extremely well when the summary is operational state rather than a transcript recap. For long-running AssistantMD tasks, the goal should be to make that recovery-card behavior explicit and testable before goals depend on it.

The compaction prompt strategy should be audited against long-running work. `CHAT_HISTORY_COMPACTION_INSTRUCTION` already preserves facts, decisions, preferences, constraints, open tasks, paths, validation results, and tool outcomes. For long-running goals it should explicitly behave like a session recovery card that preserves:

- current objective and success criteria;
- active plan/step state and next action;
- open blockers, unresolved questions, and user check-in requirements;
- artifact refs, source refs, file paths, and validation evidence;
- failed attempts, retry/cancellation state, and uncertainty;
- budget/context pressure or compaction trigger reason.

The summary should merge prior summaries with newer turns idempotently: keep what still governs future work, remove superseded detail, and avoid accumulating stale narrative. Automatic compaction should remain settings-controlled and auditable. Ordinary chat can continue to use the existing `compaction_type` policy. Long-running mode may need an explicit per-goal policy such as `inherit`, `suggest`, `auto_at_threshold`, or `pause_for_user`. Any automatic compaction should emit a clear lifecycle event and update session/goal state with compaction id, trigger reason, estimated tokens, threshold, keep-recent count, preserved recent slice, and prompt contract version.

### 3. Add a Small `goal_ops` Primitive

Create a new SQLite-backed subsystem, likely `core/goals/`, but keep the scope intentionally small. It should support bounded knowledge-work runs tied to a vault workspace or vault-maintenance scope, not a general autonomous-agent framework.

Candidate tables:

- `goal_runs`: goal id, vault, workspace path or vault-wide scope, session id, source, title/objective, status, active task id, current phase, created/updated/finished timestamps, last checkpoint id.
- `goal_steps`: ordered plan items with status, attempt count, assigned executor type (`chat`, `workflow`, `delegate`, `tool`, `user`), started/finished timestamps, and compact status text.
- `goal_events`: append-only timeline with stable event names and payload JSON.
- `goal_artifacts`: durable references to markdown files, cached artifacts, summaries, citations, workflow outputs, and child results.
- `goal_checkpoints`: compact recovery snapshots containing objective, current plan, completed work, open questions, constraints, artifacts, and latest failure/progress state.

Defer `goal_children` until there is evidence that durable child work is needed beyond existing `delegate` and `workflow_run(start)`.

Expose the subsystem through a small `goal_ops` tool/helper:

- `create`: create a workspace-scoped or vault-maintenance goal, optionally linking markdown files.
- `get`: return current state, latest checkpoint, linked files, and active task if any.
- `list`: filter by vault, workspace, status, or recent activity.
- `update`: update status, current step, checkpoint summary, or artifact refs.
- `add_event`: append structured progress/failure/check-in events.
- `attach_task`: connect an execution task or workflow run to the goal.
- `archive`: retire a goal without deleting its markdown artifacts.

`goal_ops` should not decide how to pursue a goal. Chat agents and workflows decide what to do; `goal_ops` only records durable state and links artifacts.

Markdown remains the human-facing source of truth. A default workspace might contain:

- `goal.md`: objective, scope, success criteria, check-in preference.
- `progress.md`: current phase, completed work, blockers, next action.
- `sources.md`: research/source notes and citations.
- `draft.md` or user-chosen output files.

The ledger should link to these files rather than replacing them. Keep `TaskCoordinator` as the process-local execution handle, but mirror lifecycle changes into the durable ledger when a run opts in. On startup, reconcile non-terminal durable runs into `interrupted` or `recoverable` states instead of pretending they never existed.

### 4. Add Optional Bounded Work Session Support

Add a user-facing "work on this goal" path for chat and workflows after hardening and `goal_ops` exist. The first implementation can be conservative:

- A chat command/API starts or attaches to a `goal_run` associated with the current workspace folder or vault-wide maintenance scope.
- The agent writes or updates markdown files in that workspace for goal/progress/source notes.
- Each model turn updates `goal_steps` before and after meaningful work.
- If the model needs a long workflow, it uses `workflow_run(start)` and records the task id under the active step.
- If the model needs focused research judgment, it can use normal bounded `delegate` calls that return compact summaries and/or artifact paths.
- At terminal states, the model marks the goal `completed`, `blocked`, `cancelled`, or `needs_user_input` with evidence.

Do not replace ordinary chat. This should be opt-in for complex goals where overhead is justified.

### 5. Make Checkpoints Contractual

Add a goal checkpoint writer that runs:

- before compaction,
- after each completed step,
- before/after a background workflow starts,
- before waiting on user input,
- on recoverable model/API failure,
- on cancellation/timeout.

Each checkpoint should be structured JSON, not freeform markdown:

- objective and success criteria,
- completed steps and evidence,
- active step and next action,
- open questions/blockers,
- artifacts and file paths,
- source/citation references where relevant,
- usage/budget summary,
- recovery instructions for the next run.

Context assembly should be able to load the latest checkpoint as a compact, high-priority context layer.

### 6. Add Budget and Usage Accounting

Persist real usage when provider/Pydantic AI returns it, not only estimates:

- per model request: model alias/provider, input tokens, cached input tokens, output tokens, reasoning tokens, total tokens, duration, retry count;
- per tool/delegate/workflow step: estimated result tokens, artifact/cache usage, output truncation;
- per goal: total tokens, budget, remaining budget, projected budget risk.

Expose budget policy:

- `warn_only`,
- `pause_for_user`,
- `auto_compact_then_continue`,
- `stop_at_budget`.

Start with goal-level reporting and validation events before attempting aggressive cost optimization.

### 7. Treat Durable Child Work as Later, Not Foundational

Keep the existing synchronous `delegate` for quick bounded work. Do not add durable child subtasks in the first implementation unless validation shows existing delegate/workflow composition is insufficient.

If needed later, add a separate `delegate_start` or `subtask_run` capability for long-running subtasks:

- creates a child `goal_run` or durable child record,
- has explicit objective, scope, tools, output schema, token/time budget, and artifact contract,
- can run concurrently under a configured child concurrency limit,
- returns a child id immediately,
- parent can poll/join/cancel,
- child final output is compact and references persisted artifacts.

This avoids overloading `delegate` with background semantics and preserves today's simpler tool contract. For the initial knowledge-work target, normal `delegate` plus workspace markdown artifacts should cover most cases.

### 7. Add User Check-In States

Represent user interaction as durable state:

- `needs_user_input`: agent cannot safely continue without a decision;
- `awaiting_approval`: user must approve a risky action, budget extension, or workflow;
- `checkpoint_review`: agent pauses after a milestone for user steering.

Expose these through `/api/goals/{goal_id}`, UI task panels, and chat session status. A resumed user reply should attach to the pending checkpoint and continue the same goal rather than start an unrelated turn.

### 8. Build One Goal Timeline

Add a goal detail API that returns:

- goal metadata and current status,
- plan steps,
- active task/child statuses,
- artifacts,
- usage summary,
- ordered event timeline,
- latest checkpoint summary,
- retry/failure history.

This should aggregate existing task lifecycle events, chat tool events, vault mutation groups, workflow results, delegate audits, and new goal events. It should be user-facing enough for audit, and structured enough for validation.

## Phased Implementation Plan

### Status

Started Phase 0/1 with four hardening slices:

- Added deterministic validation for parallel tool-call batches and orphaned tool returns.
- Added a shared tool-history integrity helper for provider-native chat messages and stored message payloads.
- Made `retrieve_history(...)` preserve adjacent multi-tool-call/multi-tool-return batches as one atomic `ToolExchangeBatch`.
- Added tool-history integrity metadata/events to `retrieve_history(...)` and chat compaction planning.
- Preserved `ToolExchangeBatch` through `assemble_context(...)` and authoring context normalization.
- Added deterministic validation for retryable/permanent/configuration tool failure metadata.
- Added a shared `FailureClassification` helper and migrated DuckDuckGo search, Tavily search, and Tavily extract exception paths to structured `ToolReturn` failure envelopes.
- Added accepted-turn failure recovery markers for streaming/chat failures that persist a user turn without an assistant response.
- Exposed the latest unfinished-turn marker through chat session detail and injected ephemeral recovery context into the next chat preflight.
- Added execution task heartbeat fields and workflow heartbeat events for background workflow tasks.
- Added `workflow_run(status)` heartbeat age/stale visibility and queue reason output.

Remaining hardening work should continue with broader structured failure adoption and API-safe error summaries before starting `goal_ops`.

### Phase 0: Hardening Probes and Contracts

Goal: expose current brittle points with deterministic validation before adding `goal_ops` or a new orchestration layer.

Deliverables:

- `tool_history_integrity.py` scenario for parallel tool-call batches, orphaned calls/returns, and duplicate ids. Initial coverage for parallel batches and orphaned returns is complete; orphaned calls and duplicate ids remain useful follow-up probes.
- `structured_tool_failure.py` scenario for retryable/permanent/configuration failure classification. Initial coverage is complete for the shared classifier, DuckDuckGo search failures, and Tavily search failures.
- `streaming_failure_resume_context.py` scenario for accepted-user/no-assistant failure recovery context. Initial coverage is complete in `chat_stream_failure_logging.py`.
- `workflow_heartbeat_stall.py` scenario that demonstrates how a long-running task can look active while making no progress. Initial heartbeat/stale status coverage is complete in `workflow_run_async.py`.
- Shared inventory of which tool operations are idempotent, retryable, non-idempotent, or external-effecting.
- Draft contracts for `FailureClassification`, tool-history integrity checks, task heartbeat metadata, and resume-context failure markers.

Exit criteria:

- The riskiest current failure modes are represented by failing or pending validation assertions.
- The intended hardening contracts are documented before implementation.
- No user-facing long-running-goal behavior is introduced yet.

### Phase 1: Existing Primitive Hardening

Goal: make current chat, context, workflow, and tool behavior reliable enough for longer knowledge-work turns.

Deliverables:

- Shared tool-history integrity helper used by `retrieve_history`, compaction split logic, session fork/prefix logic, and chat/context preflight where appropriate. Initial helper coverage is complete for `retrieve_history` and compaction diagnostics; session fork/prefix and chat/context preflight remain follow-ups.
- Batch-safe history retrieval for adjacent multi-tool-call/multi-tool-return messages. Complete for `retrieve_history(...)` and `assemble_context(...)`.
- Structured `FailureClassification` or `ErrorEnvelope` helper. Initial `FailureClassification` helper is complete for tool failure envelopes.
- Structured failure metadata for web/search/extract tools and selected API-facing tool errors. Initial DuckDuckGo search, Tavily search, and Tavily extract exception paths are complete; Tavily crawl, browser, model/provider retries, and API-facing errors remain follow-ups.
- Agent-safe API error summaries with stable `error_type`, `phase`, `retryable`, `suggested_action`, and relevant ids.
- Streaming failure marker or event that future context assembly can include when a user turn was accepted but no assistant response persisted. Initial marker, session detail exposure, next-turn context injection, and success clearing are complete.
- Heartbeat/progress metadata updates for workflows and long-running tool/workflow paths. Initial workflow task heartbeat metadata, validation events, and `workflow_run(status)` visibility are complete.
- Partial delegate audit/progress preservation where feasible for timeout/usage-limit failures.

Exit criteria:

- Agents receive retry/permanent/configuration classifications instead of only prose for targeted tools.
- Retrieved/compacted/reassembled history preserves valid tool-call protocol units.
- Failed long chat turns leave enough durable context for the next turn to recover.
- P0 risks addressed: tool pairing, non-actionable errors, accepted-turn failure ambiguity.

### Phase 2: Task Progress, Heartbeats, and Retry Policy

Goal: make existing background work observable and recoverable without adding a goal layer.

Deliverables:

- Heartbeat/progress metadata updates for workflows and long-running tool/workflow paths.
- Queue age and stalled-task warnings.
- `workflow_run(status)` improvements that return progress, heartbeat age, blocking reason, and artifact refs when available.
- Provider/API retry policy for retryable model/network failures.
- Validation events for retry scheduled/succeeded/exhausted and task heartbeat/stall transitions.
- Clear cancellation result language distinguishing rolled-back local mutations, retained artifacts, and external/unknown effects where the current system can know.

Exit criteria:

- "Running" work has visible progress or visible lack of progress.
- Stalled or queued work is visible before users assume it is productive.
- P0/P1 risks addressed: silent stalls, retry classification, cancellation ambiguity.

### Phase 2A: Automatic Compaction and Context Window Policy

Goal: make context-window management reliable, automatic when appropriate, and auditable for long-running knowledge work before adding a goal ledger.

Deliverables:

- Audit `CHAT_HISTORY_COMPACTION_INSTRUCTION` against long-running task needs and Codex-style recovery-card behavior: objective, success criteria, active plan/step state, artifact refs, source refs, validation evidence, open blockers, failed attempts, uncertainty, user check-in requirements, and next action.
- Make repeated compaction idempotent: summary plus newer turns should produce a fresher recovery state without accumulating stale narrative or losing the active thread.
- Define automatic compaction policy for long-running mode: inherit ordinary chat settings, force suggested mode, auto at threshold, or pause for user approval.
- Add explicit compaction trigger metadata: `trigger=manual|tool|auto_threshold|goal_policy`, estimated tokens, threshold, keep-recent count, prompt contract version, and reason.
- Add validation for automatic post-turn compaction when `compaction_type: auto` crosses threshold, including that the summary preserves long-running task state and emits auditable trigger metadata.
- Decide whether long-running goals need a separate setting from ordinary chat, such as `goal_compaction_policy`, or whether `goal_ops` should pass an explicit policy per run.

Exit criteria:

- Automatic compaction behavior is deliberate, settings-controlled, and visible to user/agent audit.
- Compaction summaries behave as operational recovery cards, not transcript recaps.
- Repeated compaction preserves the active thread across multiple rounds.
- Long-running mode does not silently lose plan state, evidence, blockers, or user check-in requirements.

### Phase 3: Minimal `goal_ops` Ledger

Goal: add a small composable primitive for workspace-scoped goal state after the underlying operations report reliable state and failures.

Deliverables:

- SQLite schema/service/API for `goal_runs`, `goal_steps`, `goal_events`, `goal_artifacts`, and `goal_checkpoints`.
- `goal_ops` tool/helper with `create`, `get`, `list`, `update`, `add_event`, `attach_task`, and `archive`.
- Workspace binding: a goal can point at a vault-relative workspace folder or declare vault-wide maintenance scope.
- Markdown links: a goal run can point at user-owned `goal.md`, `progress.md`, `sources.md`, draft files, or other workspace artifacts.
- Process-local execution task lifecycle mirrored into durable goal events when a task is associated with a goal.
- Startup reconciliation for non-terminal durable goals/tasks into `interrupted` or `recoverable`.
- Read-only API detail sufficient for audit.

Exit criteria:

- Existing chat/workflow behavior remains unchanged unless a request or script explicitly uses `goal_ops`.
- `goal_ops` records state and links artifacts but does not decide how to pursue goals.
- Restart recovery is deterministic and visible for opted-in goals.
- P0 risks addressed: process restart ambiguity and basic audit spine.

### Phase 4: Goal Checkpoints and Context Recovery

Goal: let a workspace-scoped knowledge-work goal resume coherently across turns, compaction, and process restarts.

Deliverables:

- Structured checkpoint writer/reader.
- Checkpoints before/after meaningful steps, compaction, user check-ins, background workflow starts, and recoverable failures.
- Context assembly support for latest goal checkpoint.
- Stale checkpoint detection using file hashes/session revisions/source refs where available.
- Goal-level usage accounting with provider-reported usage where available and estimates as fallback.

Exit criteria:

- A resumed goal can explain current objective, completed evidence, next action, open blockers, known uncertainty, and latest failure/progress state.
- Markdown remains the user-facing workspace record; SQLite provides recovery and coordination state.
- P1 risks addressed: stale context, compaction recovery, cost opacity.

### Phase 5: Optional Goal-Aware Chat and Workflow Execution

Goal: make goal pursuit explicit and measurable while keeping ordinary chat lightweight.

Deliverables:

- Opt-in `start_goal` / `goal_id` chat API path.
- Step state updates around model/tool/workflow activity.
- Budget policies: `warn_only`, `pause_for_user`, `auto_compact_then_continue`, `stop_at_budget`.
- Completion criteria/evidence checks before marking a goal complete.
- Durable states for `needs_user_input`, `awaiting_approval`, and `checkpoint_review`.
- Resume semantics that attach the user's reply to the pending checkpoint.

Exit criteria:

- Ordinary chat stays unchanged.
- Long-running mode tracks objective, steps, budget, evidence, check-ins, and terminal status.
- P1 risks addressed: premature completion, plan drift, check-in ambiguity.

### Phase 6: Later Enhancements Only If Needed

Goal: support more advanced orchestration only if bounded knowledge-work use cases prove existing `delegate`, `workflow_run(start)`, and `goal_ops` are insufficient.

Possible deliverables:

- Durable child-subtask capability separate from synchronous `delegate`.
- Child objective/scope/tool/output/budget contracts.
- Child polling/join/cancel operations.
- Duplicate-work detection and child concurrency limits.
- UI for active goal, plan, child tasks, artifacts, usage, queue/stall status, and check-in actions.

Exit criteria:

- Added only with concrete validation-backed need.
- P1/P2 risks addressed: delegate churn, over/under-delegation, lost child progress, opaque autonomy.

### Explicit Non-Goals for Early Phases

- Do not make all chats goal runs.
- Do not add autonomous background continuation for ordinary chat.
- Do not introduce parallel durable subagents before the goal ledger and checkpoints exist.
- Do not optimize for multi-day autonomous execution as the primary case.
- Do not model this primarily around coding-agent project execution.
- Do not adopt Temporal/LangGraph until the minimal AssistantMD-native ledger proves insufficient.
- Do not attempt to solve every P2 risk in the first implementation pass.

## Affected Areas

Immediate hardening surfaces:

- `core/authoring/helpers/history/retrieve.py`: batch-safe tool exchange retrieval and orphan detection.
- `core/chat/compaction.py`: shared tool-history integrity checks and recovery-safe compaction inputs.
- `core/chat/chat_store.py`: session fork/prefix tool-pair handling and tool-event consistency checks.
- `core/chat/executor.py`: streaming failure recovery markers, structured failure handling, and later usage accounting.
- `core/llm/capabilities/chat_tool_output_cache.py`: structured tool result/failure metadata and cache/artifact refs.
- `core/tools/web_search_tavily.py`, `core/tools/web_search_duckduckgo.py`, `core/tools/tavily_extract.py`, and similar external tools: structured retryable/permanent/configuration failure returns.
- `core/tools/delegate.py`: preserve partial child audit/progress where feasible; keep the current synchronous delegate contract stable.
- `core/tools/workflow_run.py`: richer status output with progress, heartbeat age, blocking reason, and artifacts.
- `core/runtime/execution_tasks.py` and `core/runtime/workflow_governor.py`: heartbeat/progress metadata, queue age, stall warnings, and later goal-event mirroring.
- `api/utils.py`, `api/models.py`, `api/services.py`, `api/endpoints.py`: agent-safe error envelopes and later goal APIs.
- Settings: retry policy, heartbeat/stall thresholds, and later goal budgets/checkpoint cadence. This touches persisted `system/settings.yaml`, but not secrets.

Later `goal_ops` surfaces:

- `core/goals/` or equivalent: durable workspace-scoped goal ledger.
- `core/authoring/helper_catalog.py` and `core/tools/`: expose `goal_ops` to workflows and chat.
- `static/`: goal status, plan, usage, checkpoint review, and audit timeline UI after the primitive exists.
- `docs/architecture/`: document hardening contracts first, then goal orchestration once behavior exists.
- Persistence: add a new SQLite database under `/app/system`, or extend an existing system database with explicit migrations.

## Validation Targets

Use deterministic scenarios to lock down each slice before or alongside implementation:

- `tool_history_integrity.py`: persist histories with parallel tool calls, multiple returns, orphaned calls/returns, and duplicate tool ids; assert retrieval, compaction, fork, and context assembly preserve or reject them deterministically.
- `structured_tool_failure.py`: force web/search/provider failures and assert the agent receives structured retryable/permanent/configuration classifications, not only prose.
- `delegate_partial_failure_audit.py`: force delegate timeout after one child tool event and assert partial audit/progress survives.
- `workflow_heartbeat_stall.py`: run a workflow that stops emitting progress and assert status/checkpoint surfaces a stalled or no-heartbeat warning.
- `streaming_failure_resume_context.py`: fail a streaming turn after accepted user persistence and assert resumed context includes a structured failure marker.
- `auto_compaction_context_policy.py`: configure automatic compaction, exceed threshold during a long-running-style session, run multiple compaction rounds, and assert trigger metadata, prompt contract version, and recovery-card preservation of objective, plan, artifacts, blockers, failed attempts, and next action.
- `llm_retry_policy.py`: fake provider/network failures and assert retry events, backoff classification, and no retry for permanent errors.
- `goal_ops_lifecycle.py`: create a workspace-scoped goal, update plan steps, attach artifacts/tasks, archive it, and assert API/tool state plus validation events.
- `goal_task_restart_recovery.py`: create a durable goal with a simulated active task, restart runtime, assert it reconciles to `interrupted` or `recoverable`.
- `goal_checkpoint_context.py`: write a checkpoint, compact/assemble context, assert the latest checkpoint is included as structured context.
- `goal_usage_budget.py`: run deterministic test-model turns with synthetic usage metadata, assert goal usage aggregation and budget status.
- `goal_user_checkin.py`: pause for user input, resume with a reply, assert continuation uses the same goal id and checkpoint.
- `durable_child_subtask.py`: only if Phase 6 is pursued; start child work, poll/join/cancel, assert parent timeline and child artifact references.

Maintain existing scenarios for workflow async/cancellation, chat cancellation, delegate guardrails, compaction, and vault rollback.

## Open Questions

- Should goal orchestration live primarily in chat, workflows, or a new shared subsystem? Recommendation: shared `goal_ops` primitive with chat/workflow adapters, but only after hardening existing primitives.
- Should we adopt Temporal/LangGraph directly? Recommendation: not in the first slices. AssistantMD already has SQLite persistence, workflows, validation, and task primitives. Harden those first; revisit Temporal/LangGraph only if native checkpoint/retry semantics become too costly to maintain.
- Should all chat turns become goals? Recommendation: no. Keep normal chat lightweight and make long-running mode explicit.
- How much autonomy should background goals have after user disconnect? Recommendation: existing workflows and explicit user-started background workflow tasks can continue; ordinary chat should remain request/stream scoped.
- How should we expose budgets? Recommendation: start with warn/pause behavior and clear usage telemetry, not automatic aggressive pruning.

## Source Notes

- Anthropic, "Effective harnesses for long-running agents" (Nov. 26, 2025): initializer/coding-agent split, feature list, progress file, incremental work, clean session endings.
- Anthropic, "How we built our multi-agent research system" (Jun. 13, 2025): orchestrator-worker subagents, cost tradeoffs, delegation heuristics, observability, checkpoints, durable recovery, final-state/checkpoint evaluation.
- Anthropic, "Effective context engineering for AI agents": curated tools, compaction tuning, structured note-taking, subagent context isolation.
- LangGraph persistence docs: checkpointers and stores for thread state, fault tolerance, human-in-the-loop, and long-term memory.
- OpenAI Agents SDK docs: tracing, sessions, usage tracking, max-turn/error handling.
- Pydantic AI retry docs: provider HTTP retry transports with backoff and `Retry-After` support.
- Temporal/Pydantic AI durable execution article: replay-based durable execution for API failures, restarts, deploys, and human-in-the-loop waits.
- OpenAI Codex repository inspection: resumable thread ids, structured turn/item events, token usage in turn events, overload retry helper, goal status/budget concepts, context compaction events, turn steering/interrupts, and subagent metadata in app-server protocol.

## Next Phase

Feature Development should continue with automatic compaction policy and prompt-strategy audit before `goal_ops`. The next concrete work should define and validate automatic compaction behavior for long-running-style sessions, then revisit whether remaining structured API error summaries block the minimal `goal_ops` ledger. `goal_ops` should remain deferred until context-window management is safe and auditable.
