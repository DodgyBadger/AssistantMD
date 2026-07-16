# Activity Log And Workflow Health Plan

## Objective

Make it reliable to answer two different user questions:

1. Did a workflow run, and what was its outcome?
2. What happened in AssistantMD around a particular time?

Workflow outcomes should be durable product state surfaced on the Dashboard.
`system/activity.log` should remain a compact diagnostic stream, not the
canonical workflow history.

## Current Findings

- `core/logger.py` rotates `system/activity.log` at 1 MiB and retains five
  backups.
- `GET /api/system/activity-log` reads only the active file. The UI requests
  the last 64 KiB and the API caps requests at 256 KiB, so retained backup
  files are invisible.
- In the inspected runtime data, the visible 64 KiB represented 141 entries
  and about five minutes of activity. Validation traffic contributed heavily,
  so this is not a production retention estimate, but it demonstrates that a
  byte tail has no useful time guarantee.
- Rotated files include tiny rollover fragments, consistent with independent
  processes racing through `RotatingFileHandler`. Python's standard rotating
  handler is not a multi-process history store.
- The largest retained event family by bytes was workflow scheduler sync. Its
  activity payload repeats complete loaded, scheduled, and disabled workflow
  arrays where a user-facing count summary would suffice.
- `validation/core/runner.py` uses the default logger sinks, so validation-runner
  events enter the user-facing activity log. Other events use
  `add_sink("validation")`, which retains the default activity sink rather than
  making the event validation-only.
- Workflow `last_run_time`, `last_status`, and `last_error` come from the
  process-local dictionary in `core/scheduling/job_history.py`. Restarting the
  application clears them.
- APScheduler reports a job as executed when it returns normally, even when the
  returned `WorkflowExecutionResult` has a domain status of `failed`. The
  process-local status can therefore say `completed` for a failed workflow.
- The Dashboard status badge represents only configuration state
  (`scheduled`, `enabled`, or `disabled`). It does not show the latest workflow
  outcome.
- Workflow load errors are available through API configuration-error data but
  are not presented with the Dashboard workflow list. A workflow that cannot
  load can therefore disappear from the list instead of appearing unhealthy.
- Execution tasks are intentionally process-local. Vault Activity is durable
  but mutation-oriented, so a workflow that fails before changing a file may
  have no useful Vault Activity record. Neither should be repurposed as
  workflow run history.

## Recommended Design

### 1. Durable Workflow Run Ledger

Add a subsystem-owned `workflow_runs` system database. Record every workflow
attempt routed through `WorkflowGovernor`, regardless of whether its source is
the scheduler, API, a tool, or a system action.

Each run should store:

- a stable run id, workflow id, workflow name, and vault;
- source, optional execution task id, and optional requested step;
- queued, started, and terminal timestamps;
- terminal status (`completed`, `failed`, `skipped`, `cancelled`, `timed_out`,
  or `missed`);
- a bounded reason/message and structured failure classification;
- execution duration and compact output-file metadata.

Create the run before the governor waits on execution gates. Update it at the
same points where the governor already sets task metadata and domain terminal
status. The returned `WorkflowExecutionResult.status`, not merely the
APScheduler event type, is authoritative.

Extend the scheduler listener to record `EVENT_JOB_MISSED`. Scheduler dispatch
errors that occur before the governor creates a run should also create a
terminal workflow run with a scheduler-phase failure, while normal governor
runs must not be duplicated.

Use the centralized system migration registry for the new database. Retain
detailed runs for 90 days and at most 500 rows per workflow, while preserving a
latest-outcome projection so a quiet workflow does not lose its last known
state. These should be opinionated defaults for v0.7.0 rather than new settings.

### 2. Workflow Health On The Dashboard

Replace workflow last-run data derived from the process-local scheduler listener
with the durable latest-run projection.

Keep enablement/schedule state separate from execution health. Add a **Last
Result** presentation with a clear status badge, timestamp, and source. A
failed, timed-out, or missed latest attempt should be visually prominent and
offer its concise reason. A later successful run should return current health
to successful while older attempts remain available in run history.

Add an attention summary above the workflow table for:

- workflows whose latest attempt failed, timed out, or was missed;
- current workflow load errors, including files that are absent from the normal
  loaded-workflow list.

Allow opening a compact per-workflow run history from its row. The initial
scope does not need alert delivery, acknowledgements, or failure notifications;
the Dashboard is the durable inspection surface.

### 3. Time-Retained System Activity

Keep JSONL as the diagnostic format, but replace the current opaque byte-window
contract with time-bounded segmented retention:

- retain 30 calendar days by default;
- enforce a generous total-size ceiling to prevent an accidental logging loop
  from consuming unbounded disk;
- keep segment rollover single-writer or protected by an inter-process lock;
- expose the earliest retained timestamp when the size ceiling shortened the
  nominal retention window.

The API should return parsed entries with cursor pagination and server-side
filters for time, level, tag, and free-text search across retained segments.
The UI should load a recent page, support **Load older**, and apply searches to
the retained history rather than only the bytes already in the browser. Preserve
an export path for sharing raw JSONL diagnostics.

### 4. Activity Volume Audit

Bring emitters back into alignment with
`docs/agent-guides/activity-logging.md` before increasing retention:

- route validation runs exclusively to validation artifacts, including early
  bootstrap events from validation processes;
- replace `add_sink("validation")` with `set_sinks(["validation"])` for
  helper-level and assertion-only events;
- keep workflow scheduler sync activity to one compact count/decision summary,
  with detailed workflow arrays in validation artifacts only;
- keep debug events out of System Activity;
- audit the highest-volume tags for repeated helper successes and oversized
  payloads, preserving user-visible starts, meaningful decisions, terminal
  outcomes, warnings, and failures.

Increasing file sizes without this audit would retain more noise, while only
adding workflow history would leave the general diagnostic viewer unreliable.
Both corrections are required.

## Contract-Sensitive Areas

- `core/logger.py` activity sink and rollover behavior
- validation runtime sink selection
- `core/runtime/workflow_governor.py` terminal lifecycle coverage
- `core/scheduling/job_history.py` and APScheduler event handling
- centralized system database declarations and migrations
- `/api/status` workflow summaries
- `/api/system/activity-log` response and query contract
- Dashboard workflow rendering and System Activity filtering
- persisted runtime data under `/app/system`

## Implementation Slices

### Slice 1: Durable Outcomes

- Add the workflow-run schema, repository, migrations, and retention cleanup.
- Integrate run creation/finalization with every governor outcome.
- Capture scheduler misses and pre-governor dispatch failures without duplicate
  rows.
- Replace workflow status API fields sourced from process-local history.

### Slice 2: Workflow Health UI

- Add latest-run and run-history API models.
- Render separate configuration and execution-health states.
- Surface current load errors and recent unhealthy outcomes above the workflow
  list.
- Add the per-workflow history view.

### Slice 3: Diagnostic Retention And Query

- Make activity segmentation and pruning time-based and concurrency-safe.
- Add structured, paginated server-side activity queries and raw export.
- Update the System Activity viewer for retained-history search and pagination.

### Slice 4: Noise Reduction

- Isolate validation output from persistent System Activity.
- Compact scheduler sync records.
- Correct additive validation sinks and other high-volume emitters identified by
  an event/byte-volume audit.
- Document the resulting current contracts in the scheduler, runtime, and
  activity-logging architecture guides.

## Validation Targets

Add focused scenarios that prove:

- a workflow's latest outcome and history survive application restart;
- a returned failed workflow result is stored and displayed as failed even when
  APScheduler reports normal function completion;
- failed, timed-out, cancelled, skipped, and missed runs each finalize once;
- API, scheduler, and tool-triggered runs use the same ledger path;
- current workflow load errors appear in Dashboard health;
- activity queries page and filter across multiple retained segments;
- retention pruning reports the actual earliest retained timestamp;
- validation execution does not append to the persistent System Activity log;
- scheduler sync activity contains compact counts, not complete workflow lists.

Maintainers should run the relevant targeted scenarios and full validation per
the repository validation workflow.

## Non-Goals

- Persisting the generic execution-task coordinator
- Treating Vault Activity as workflow monitoring
- External notifications or alert delivery
- Inferring that a workflow should have run while AssistantMD was offline beyond
  explicit APScheduler missed-job events
- Making retention settings user-configurable in the first implementation

## Next Phase

Continue Feature Development with cursor pagination and server-side filtering
for retained System Activity. The durable workflow ledger, Dashboard health and
run-history surface, daily retained activity segments, multi-segment API reads,
and primary validation/scheduler noise reductions are implemented. A broader
emitter audit and raw retained-log export remain open.
