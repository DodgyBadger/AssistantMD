# Activity Logging

## Purpose

`system/activity.log` is the user-facing diagnostic record. It should let a user verify that major AssistantMD operations are working and share useful bug context without opening validation artifacts, Logfire traces, or database internals.

For each user-visible operation, activity logging should answer:

- what started
- what important decision was made
- what completed, skipped, failed, or was cancelled
- which vault, session, workflow, file, job, or task identity the user can search for
- what a maintainer should inspect next if the operation failed

## Policy

- Keep activity events user-diagnostic, not purely implementation-diagnostic.
- Prefer one start event, one decision summary, and one terminal event over per-item logging.
- Use validation-only logs for high-volume loops, helper internals, and scenario assertions that are not useful to users.
- Keep per-file mutation detail in Vault Activity; System Activity should summarize task-level effects.
- Include stable `event` and `status` fields for lifecycle logs.
- Include stable identity fields when available: `vault_name`, `session_id`, `workspace_path`, `task_id`, `workflow_id`, `workflow_name`, `job_id`, `source`, `reason`, `error_type`, and `error`.
- Avoid sensitive or bulky values: never log secret values, full prompts, full tool arguments, full model outputs, or imported document text. Prefer counts, lengths, paths, refs, hashes, and short errors.
- Use stable subsystem tags. Do not create many near-duplicate ad hoc tags for the same user workflow.

## Validation Sink

Use `logger.set_sinks(["validation"])` for events that should only support scenario assertions or local debugging.

Use activity-visible logging for:

- user-triggered operation lifecycle summaries
- background jobs a user may need to verify
- failures, skips, cancellations, and retries with user-visible impact
- concise terminal summaries that correlate to execution tasks or Vault Activity

Avoid `logger.add_sink("validation")` for helper-level success events unless the event is intentionally useful in both validation artifacts and `system/activity.log`.

## Recommended Event Shape

```python
logger.info(
    "Chat turn completed",
    data={
        "event": "chat_turn_completed",
        "status": "completed",
        "vault_name": vault_name,
        "session_id": session_id,
        "workspace_path": workspace_path,
        "task_id": task_id,
        "model": model_alias,
        "tool_call_count": tool_call_count,
    },
)
```

Failures should include `error_type` and a concise `error`. Add tracebacks only when the log is already an error diagnostic path and the traceback is useful to maintainers.

## Subsystem Guidance

- Runtime: log bootstrap, reload, migration, scheduler, and configuration-health summaries.
- API/UI: log user-triggered configuration mutations with stable `event`, target identity, and `restart_required`.
- Execution tasks: keep lifecycle events as the common spine; owning subsystems should add domain terminal summaries.
- Vault state: keep per-file detail out of System Activity by default; log refresh, cleanup, rollback, and mutation failure summaries.
- Authoring/context: log context-template run started/completed/failed; keep successful helper calls validation-only.
- Scheduler/workflows: log sync decisions and terminal scheduled/manual workflow outcomes with searchable workflow names.
- Chat: log chat turn started/completed/failed/cancelled with session, workspace, model, context template, and compact tool counts.
- Session summaries: log user-visible summary mutations and summarize-session terminal outcomes.
- LLM/tools: persist per-tool chat events structurally; activity should summarize long-running/external tool outcomes and failures.
- Multimodal: log compact attach/fallback counts and reason codes, never image bytes.
- Ingestion: log batch scan/enqueue decisions and per-file terminal summaries, including selected strategy and OCR fallback details.

## Review Checklist

- Can the activity log be filtered by a user-known identity such as session id, workflow name, filename, or workspace?
- Is the event stable enough for validation and future audits?
- Is the row compact enough for a byte-limited activity-log tail?
- Did helper-level success noise stay out of System Activity?
- Does the failure path include enough information to decide the next inspection step?
- Are secrets, prompts, large outputs, and document contents excluded?
