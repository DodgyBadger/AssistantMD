# Activity Logging Audit Plan

## Objective

Improve `system/activity.log` so a user can verify that major AssistantMD subsystems are working as expected and can share useful bug context without needing to inspect validation artifacts, backend traces, or database internals.

The activity log should answer, for each user-visible operation:

- What started?
- What important decision was made?
- What completed, skipped, or failed?
- What vault/session/workflow/file/job identity should the user search for?
- What should a maintainer inspect next if the operation failed?

## Current Observations

`UnifiedLogger` writes to activity and Logfire by default. `add_sink("validation")` writes to activity plus validation, while `set_sinks(["validation"])` writes only validation artifacts. The current code mixes those choices by subsystem, which makes validation coverage stronger than user-facing activity coverage.

The System activity-log UI reads a byte-limited tail of `system/activity.log` and filters client-side. That favors compact summary events and stable searchable fields over high-volume per-loop events.

Vault Activity is separate from System Activity. Vault Activity is the right surface for task-scoped file mutations and retained snapshots. System Activity should link or summarize those effects rather than duplicating every mutation row in detail.

## Recommended Logging Policy

1. Keep activity events user-diagnostic, not purely implementation-diagnostic.
2. Prefer one start event, one decision summary, and one terminal event over per-item logging.
3. Use validation-only logs for high-volume loops, helper internals, and deterministic scenario assertions that are not useful to users.
4. Include stable identity fields consistently:
   - `event`
   - `vault_name` or `vault`
   - `session_id`
   - `workspace_path`
   - `task_id`
   - `workflow_id`
   - `workflow_name`
   - `job_id`
   - `source`
   - `status`
   - `reason`
   - `error_type`
   - `error`
5. Avoid sensitive values:
   - never log secret values
   - avoid full prompt text, full tool arguments, full model outputs, and full imported document text
   - log counts, lengths, hashes, paths, refs, and short error messages instead
6. Use stable tags by subsystem. Do not create many near-duplicate ad hoc tags for the same user workflow.

## Subsystem Audit

### Runtime

Current state:

- Bootstrap and shutdown log to activity.
- Database migration startup check logs counts.
- Config reload records some scheduler-sync failures.
- Background vault-state refresh logs start/completion/failure.

Recommendations:

- Add a single `runtime_bootstrap_summary` activity event after successful bootstrap with scheduler status, workflow sync counts, system job counts, vault-state background refresh started, migration pending count, and configuration health.
- Add a `configuration_reload_completed` activity event whenever reload runs, including `restart_required`, config issue counts, and system scheduler sync result.
- Keep low-level startup debug detail out of activity unless it represents a failed user-verifiable startup milestone.

Validation target:

- Startup/reload scenario asserts the summary event exists with migration, scheduler, and config-health fields.

### API + UI

Current state:

- API exception handler logs unexpected API errors with traceback details.
- Many settings/model/provider/secret changes log activity.
- Activity-log endpoint returns a byte-limited tail; UI filters client-side by search, level, and tag.

Recommendations:

- Add stable `event` fields to all user-initiated configuration mutation logs, not just message text.
- Add a manual action event for activity-log refresh failures only if server-side reading fails; UI-only refresh attempts should not write server activity noise.
- Consider a future server-side activity-log query endpoint with time/tag/level/search parameters so users are not limited to filtering the current tail.

Validation target:

- API/service tests or scenario steps assert config mutation events include `event`, target identity, and `restart_required` where applicable.

### Execution Tasks

Current state:

- Task lifecycle events are strong and stable: created, started, cancel requested, ignored, completed, failed, cancelled, timed out, skipped.
- Payload includes task identity fields, status, cancellation state, and terminal reason.
- Generic execution task completion is not always enough to diagnose domain-specific results.

Recommendations:

- Keep generic task events as the cross-subsystem spine.
- For domain tasks, continue adding domain-specific terminal detail in the owning subsystem: chat, workflow, ingestion, compaction.
- Add task metadata summary fields cautiously; avoid dumping large `metadata` into every lifecycle event.

Validation target:

- Existing execution-task lifecycle scenarios remain the base contract; subsystem scenarios assert their domain terminal events can be correlated by `task_id`.

### Vault State

Current state:

- Refresh start/completion, refresh failures, cleanup, mutation failures, untracked mutations, mutation rows, snapshots, and rollback all log activity or validation.
- Per-file vault change events are validation-only unless debug is enabled, which is appropriate for noise control.
- Vault Activity provides the stronger user-facing file mutation surface.

Recommendations:

- Keep per-file manifest changes validation-only by default.
- Add or verify concise activity summaries for manual refresh, scheduled refresh, mutation-triggered refresh, rollback start/completion/failure, and cleanup.
- In rollback events, include `task_kind`, `task_label`, and affected vault/path counts when available so users can correlate with a failed chat/workflow/ingestion task.
- Avoid duplicating every `task_file_mutation_recorded` row in System Activity; consider making mutation-record rows validation-only once Vault Activity is sufficient, while keeping mutation failures and untracked warnings in activity.

Validation target:

- Vault mutation/rollback scenario asserts System Activity has rollback summary and Vault Activity has file-level details.

### Authoring

Current state:

- Workflow load successes are validation-only; load failures are activity-visible.
- Monty execution start/completion/failure currently writes to activity plus validation.
- Direct authoring tool calls and helper calls can be activity-visible and may become noisy.
- Context template loaded is activity-visible, but context section/history compilation details are validation-only.

Recommendations:

- Add a context-template activity summary per chat run: template name/source, workspace path, prior history count, assembled message count, summary section count, status, and failure phase.
- Keep helper-level events (`retrieve_history`, `parse_markdown`, `read_cache`, `pending_files`, direct tool start/completion) validation-only unless they fail.
- Keep workflow load successes out of activity as per-item events; rely on scheduler sync summary for workflow inventory.
- Ensure authoring execution events identify whether the script was a workflow, context template, or code execution tool run.

Validation target:

- Default context scenario asserts `context_template_run_completed` includes template, workspace path, and assembled message counts.

### Scheduler

Current state:

- Recent update added workflow sync summary, meaningful create/replace/remove events, terminal workflow scheduler events, and searchable workflow names.
- System scheduler jobs log sync and scheduled vault-state refresh completion.

Recommendations:

- Keep unchanged workflow job updates out of per-workflow activity.
- Add terminal activity for system scheduler job failures, but avoid successful system-job noise except for user-significant scheduled work summaries.
- Include `next_run_time` and `reason` in scheduler sync summaries for disabled/no-schedule workflows.

Validation target:

- Workflow scheduler scenario asserts searching a workflow name finds loaded/scheduled/disabled status and terminal run outcome.

### Chat Sessions

Current state:

- Chat execution logs phases and failures.
- Streaming tool call start/finish logs are activity-visible and can be noisy.
- Tool events are persisted in `chat_tool_events`, which is a better detail surface for per-tool calls.
- Cancellation and compaction have useful task and compaction events.

Recommendations:

- Add chat turn summary events: `chat_turn_started`, `chat_turn_completed`, `chat_turn_failed`, `chat_turn_cancelled`, with session, vault, model alias, context template, workspace path, tool counts, token/length estimates, and persisted message counts.
- Move streaming per-tool start/finish activity logs to validation-only, while preserving persisted `chat_tool_events` and including a compact tool summary in the chat terminal event.
- Ensure chat cancellation terminal events include session id, task id, accepted user message persisted, and assistant response omitted.

Validation target:

- Chat scenario asserts one terminal chat summary can be filtered by session id and includes tool count and status.

### Session Summaries

Current state:

- Compaction logs are strong.
- `session_ops` has some validation-only tool-call logs and error logs.
- Summary upsert/search behavior is not consistently activity-visible as a subsystem.

Recommendations:

- Add activity events for user-visible summary mutations: summary created, updated, deleted, summarize-session started/completed/failed.
- Include `session_id`, `vault_name`, `workspace_path`, `summary_status`, source history revision, and stale/fresh decision fields.
- Keep search/list operations validation-only unless they are explicit user/API operations that fail.

Validation target:

- Session summary scenario asserts summary creation/update events and workspace path are searchable.

### LLM + Tools

Current state:

- Tool calls are stored structurally in chat storage.
- Some individual tools log initialization validation-only; browser and delegate log more activity-visible lifecycle events.
- Model/tool resolution failures are not consistently summarized in activity.

Recommendations:

- Treat chat tool events as the detailed per-call record.
- Activity should log only tool lifecycle summaries for long-running or external tools: browser sessions, delegate child runs, workflow runs, code execution, web fetch/crawl/extract failures, and cache overflows.
- Add a model/tool binding summary on chat start or failure: selected model alias/provider, enabled tool ids, unavailable tool count, missing-secret count.
- Standardize tool activity payloads around `tool`, `operation`, `status`, `duration_ms`, `item_count`, `error_type`, and `error`.

Validation target:

- Tool-heavy chat scenario asserts chat terminal event includes compact tool summary and persisted tool events remain available through session detail.

### Multimodal

Current state:

- Multimodal decisions are documented but not clearly represented in activity.
- Some chat logs include attached image count; file reads return markers/fallbacks.

Recommendations:

- Add validation-only detailed image preflight events and activity-visible summaries when a user-visible multimodal decision affects behavior: images attached, images downgraded to refs, token overflow caused ref fallback, missing image refs.
- Include counts and reason codes, not image bytes or base64.
- Surface the summary through chat turn completion and file read/tool result metadata rather than separate high-volume activity rows where possible.

Validation target:

- Multimodal scenario asserts fallback reason counts are present in the chat/tool summary.

### Settings + Secrets

Current state:

- General setting, model, provider, and secret mutations log activity.
- Secret logs use secret names and value-presence booleans rather than values.
- Repair-from-template lacks a clear activity event.

Recommendations:

- Add stable `event` fields and `restart_required` to all settings/provider/model/secret mutation events.
- Add `settings_repaired_from_template` with added/pruned/backup path counts.
- Add configuration validation summary after reload with issue counts, not full secret/provider details.

Validation target:

- Settings scenario asserts mutation, repair, and reload events are searchable by setting/model/provider/secret name.

### Ingestion Pipeline

Current state:

- Recent work added job start, strategy resolution, strategy skip/failure/selected/empty, job completion/failure, source filename, selected strategy, warnings, outputs, and OCR fallback details.
- Execution task and Vault Activity cover task lifecycle and file writes.

Recommendations:

- Keep strategy-level events only while they remain compact; if imports often batch many files, consider replacing per-strategy rows with one per-job extraction summary.
- Add batch scan summary: vault, import folder, files discovered, queued, skipped duplicate, unsupported, processing mode, OCR options.
- Include source basename and stable source type in all failure paths, including unsupported sources that currently log with `metadata` rather than structured `data`.
- Ensure worker batch events include selected job ids and terminal counts without logging every queue poll.

Validation target:

- Batch ingestion scenario asserts searching a PDF filename shows scan/enqueue, strategy decision, completion/failure, and output count.

### Validation

Current state:

- Validation artifacts receive many fine-grained events through validation sink.
- Several useful validation events are intentionally not activity-visible.

Recommendations:

- Preserve validation-only detail for scenario assertions.
- Add validation checks for activity-log user journeys, not only internal validation events.
- Establish helper assertions for “activity contains event with fields” to avoid brittle raw-log matching.

Validation target:

- Add shared validation helper to parse activity log JSONL and assert event fields by tag/event/search identity.

## Prioritized Implementation Steps

1. Define a small event taxonomy and helper conventions in `core/logger.py` or a new logging utility module:
   - stable event names
   - identity field names
   - summary-vs-detail guidance
   - optional duration helper
2. Chat:
   - add chat turn started/completed/failed/cancelled summaries
   - move streaming per-tool activity logs to validation-only
   - include compact tool summary on terminal events
3. Context authoring:
   - add context-template run started/completed/failed summaries with workspace fields
   - make helper-level success events validation-only unless failing
4. Settings/runtime:
   - add configuration reload summary and stable `event` fields to config mutation logs
   - add runtime bootstrap summary
5. Ingestion:
   - add batch scan/enqueue summary
   - normalize unsupported-source warnings to structured activity events
6. Vault state:
   - review whether `task_file_mutation_recorded` should remain activity-visible now that Vault Activity is the file-level detail surface
   - strengthen rollback summary identity fields
7. Multimodal:
   - add compact fallback/attach reason summaries into chat/tool terminal metadata
8. Validation:
   - add reusable activity-log parser/assertions
   - extend one scenario per high-priority subsystem rather than creating many narrow scenarios

## Next Phase

Move to Feature Development for the first implementation slice. Recommended first slice: chat/context activity summaries, because they are highly user-visible and currently rely on scattered phase logs plus validation-only context events.

