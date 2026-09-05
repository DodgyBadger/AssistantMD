# Content Import Immediate Execution Plan

## Status

Implemented. Focused validation covers the immediate, queue-only, attribution,
batch, and durable-failure contracts. Maintainer-owned full validation remains
to be run before merge.

## Recommendation

Make `content_import(operation="submit")` process accepted jobs immediately and
await their terminal state by default. Preserve durable job creation as the
authority for status, provenance, outputs, failures, restart reconciliation,
and Vault Activity. Add an explicit top-level `queue_only` boolean, defaulting
to `false`, for callers that intentionally want background execution.

This is preferable to an opt-in `run_immediately` flag because the primary
tool caller needs the imported Markdown during the same agent turn. An opt-in
flag would preserve the failure-prone default and rely on every model and
workflow author to discover and remember the workaround. `queue_only` also
matches the existing import-scan API vocabulary and its immediate-by-default
behavior.

## Current Behavior and Constraints

- `ContentImportService.submit()` validates sources and options, creates durable
  jobs, and returns their initial queued projections.
- The scheduler-owned worker runs every 120 seconds by default, so an agent can
  wait roughly two minutes before processing even begins.
- The agent-visible tool has no way to request immediate processing. Its only
  recovery path is repeated `status` calls or unrelated attempts to advance the
  work.
- API URL import and non-queue import scans already prove that a durable job can
  be claimed and processed inline under an attributed ingestion execution task.
- ADR 0029 currently defines `submit` as prompt queue submission, so changing
  the default requires amending that decision and the public tool documentation.
- Immediate execution must not bypass job persistence, source validation,
  extraction strategy selection, vault-mutation routing, or execution-principal
  propagation.

## User-Visible Contract

### Submit

Add `queue_only: bool = false` to the `content_import` tool schema.

- With the default `queue_only=false`, create one durable job per accepted
  source, process each submitted job through the runtime ingestion task path,
  await completion, and return refreshed job projections. Each item should be
  terminal (`completed` or `failed`) and include output paths or the durable
  error and strategy provenance.
- With `queue_only=true`, retain the current behavior: return promptly with
  queued job projections for later `status` calls or scheduler processing.
- The tool description and parameter documentation should tell agents to keep
  the default for routine imports and use `queue_only=true` for large multi-file
  submissions when waiting for all extraction work would unnecessarily occupy
  the current turn. Do not make the tool silently choose a mode from batch size;
  that would make latency and result state unpredictable to callers.
- Keep `status` unchanged. Reject `queue_only=true` for `status`; an omitted or
  false value has no effect.
- Keep the existing batch limit and process immediate batch items sequentially.
  This matches the existing direct API scan behavior and avoids turning one
  tool call into an unbounded OCR/network fan-out. A later concurrency change
  should be governed centrally rather than introduced in this tool.
- Continue returning an overall successful tool envelope when submission was
  valid but an individual durable job ended in `failed`; the item already
  carries its terminal status and actionable error. Request/schema failures
  remain structured tool failures.

### Queue Races and Cancellation

The immediate-processing helper should atomically claim each queued job before
processing it. If another worker has already claimed a submitted job, wait for
that specific job to become terminal and return its refreshed projection rather
than silently returning `processing`. Avoid invoking `ingestion_worker.run_once()`
from the tool because it can select unrelated older jobs and is constrained by
the worker batch size.

If inline task setup fails after a claim, preserve the existing API invariant:
mark the durable job failed instead of leaving it stranded in `processing`.

## Implementation Scope

1. Extract the API's immediate claim/process/failure-close behavior into a
   shared ingestion orchestration helper under `core/ingestion/`. The helper
   should accept `ExecutionTaskSource` and explicit `ExecutionAuthority`, use
   `process_ingestion_job_in_task()`, and return the refreshed durable job.
2. Update `api/services/ingestion.py` to use the shared helper without changing
   current API behavior.
3. Update `core/tools/content_import.py` to expose `queue_only`, capture the
   current execution authority, process default submissions with source `tool`,
   and serialize refreshed job state.
4. Keep extraction options in `options`; do not persist `queue_only` as a job
   extraction option because it is invocation orchestration policy.
5. Update `docs/tools/content_import.md`, the tool description/docstring, and
   ADR 0029 so they describe synchronous-by-default submission and explicit
   queue-only use as the current contract.
6. Add structured validation fields for execution mode and terminal counts to
   the existing `content_import_submitted` event, without logging imported
   content or secrets.

## Validation Target

Extend `validation/scenarios/integration/core/content_import_tool.py` to prove:

- default singular submit returns a completed item and usable output without a
  manual worker run or follow-up status call;
- URL/PDF routing still returns strategy/provider/fallback provenance inline;
- `queue_only=true` returns queued state and remains cancellable before worker
  execution;
- immediate batch submission returns terminal results for every accepted item;
- immediate processing is attributed to an ingestion execution task with source
  `tool` and the current principal;
- a processing failure returns a durable failed item rather than stranding the
  job or converting a valid submission into a bad-request tool failure;
- status, vault isolation, traversal rejection, source preservation, and batch
  limits remain unchanged.

Per repository policy, the implementing agent should use focused local checks
only and ask maintainers to run the full scenario validation suite.

## Persistence and Settings Impact

No database migration, persisted job-schema change, secret change, or new
setting is needed. Existing queued jobs remain compatible. The configured
worker interval and batch size continue to govern background imports, including
`queue_only=true` submissions.

## Implementation Result

The shared immediate-processing helper is used by both API and tool adapters.
The tool exposes `queue_only=false`, documents queue-only use for large
multi-file submissions, and returns refreshed durable results after immediate
processing. Immediate submission resolves execution authority before creating
jobs, and the shared runner derives its audit scope from the persisted job's
vault. The usage guide, ADR, release notes, and integration scenario match that
contract.
