# Issue 35 - Goal 3 Plan: Workflow `max_runs` Hard Cap

## Scope
Add workflow frontmatter property:
- `max_runs` (integer > 0)

When run count reaches the cap, workflow auto-disables (`enabled: false`) and records stop reason `max_runs_reached` with relevant counters.

## Codebase Findings (Current State)
- Workflow config schema currently supports `workflow_engine`, `schedule`, `enabled`, `week_start_day`, `description`; no run-cap field yet.
- Step workflow execution path is in `workflow_engines/step/workflow.py`.
- No persistent workflow run-count store exists today (only validation harness tracks job executions for tests).
- Lifecycle enable/disable file mutation now exists in `core/tools/workflow_run.py`; this should be reused/extracted, not duplicated.

## Validation-First Contract

### User-visible artifacts
- Workflow with `max_runs: N` executes normally until cap is reached.
- On the cap-reaching run, workflow is automatically set to `enabled: false` in frontmatter.
- Subsequent scheduled runs do not continue (scheduler job removed after reload/sync).
- Run history/events clearly indicate `max_runs_reached` and counters.

### Internal artifacts
- Decision boundary event emitted when cap triggers stop.
- Existing scheduler sync events (`job_synced`, `job_removed`) remain source of truth for scheduling side effects.

### Non-negotiable invariants
- `max_runs` must be validated as integer > 0.
- Auto-disable is non-destructive: only `enabled` is changed.
- Path writes must preserve security boundaries (realpath containment, no symlink escape).
- Behavior is deterministic and idempotent at cap boundary (no repeated noisy writes/events).
- Counter updates and cap transition must be concurrency-safe (no double-increment or duplicate disable side effects under near-simultaneous completions).

## Behavioral Semantics

### Counting policy (proposed)
- Count successful workflow runs (not failed parse/setup runs).
- Count both manual and scheduled executions (single safety rail across entry points).

### Cap behavior
- If current successful count is `k` before run:
  - allow run when `k < max_runs`
  - after successful completion, increment to `k+1`
  - if `k+1 >= max_runs`, set `enabled: false`, reload workflows/scheduler, emit stop event.

### Existing disabled semantics
- Keep current product behavior: `enabled` affects scheduled runs; manual runs may still be possible unless explicitly changed.
- `max_runs` stop focuses on preventing accidental recurring scheduled execution.

## Data Model / Persistence

### New persistent state table (system DB)
Add a small workflow execution state table in `file_state.db` for this issue slice (closest existing workflow-state store):
- key: `workflow_id` (global_id)
- fields:
  - `successful_run_count` (int)
  - `last_run_at` (datetime)
  - `updated_at` (datetime)

Optional: include `max_runs_stop_at` timestamp for diagnostics.

### Why persistent store
- Required to survive restarts.
- Keeps run cap independent from scheduler in-memory state.
- `cache.db` is context/session cache and is unrelated to workflow file/pending/run-count state.
- `ingestion_jobs.db` is actively used for ingestion queue state and should remain separate for now.
- `file_state.db` already holds workflow file state (`processed_files`), making it the most pragmatic host for run-count state in goal 3.

### DB hygiene note (for issue 36 follow-up)
- Current environment shows `ingestion_jobs` table also present in `file_state.db` (likely metadata/table-registration bleed), while active ingestion rows are in `ingestion_jobs.db`.
- Goal 3 should avoid widening this bleed:
  - create only the specific max-runs table needed in `file_state.db`
  - avoid broad `create_all` calls that register unrelated tables into the wrong DB.

## Implementation Strategy

1. Add failing scenario assertions first
- New integration scenario under `validation/scenarios/integration/core/` (e.g. `workflow_max_runs.py`) covering:
  - workflow starts enabled with `max_runs: 2`
  - run #1 completes, still enabled
  - run #2 completes, then auto-disabled
  - stop reason event includes `max_runs_reached` and counters
  - scheduler side effect confirms job removed/disabled state after cap
  - explicit post-cap manual run behavior assertion (to lock intended semantics: scheduled-stop only vs full-stop)

2. Extend workflow config schema
- Update `core/workflow/parser.py::WorkflowConfigSchema`:
  - add `max_runs: Optional[int]`
  - validate `> 0` when present
- Thread through loader/definition:
  - `core/workflow/definition.py`
  - `core/workflow/loader.py`

3. Add workflow run-state manager
- Implement persistent run-count manager (new module under `core/workflow/` or `core/utils/`), with:
  - get count
  - increment successful count
  - read-after-write semantics

4. Hook cap logic into step workflow execution
- In `workflow_engines/step/workflow.py`, after successful run completion:
  - increment successful count
  - evaluate cap
  - when reached: auto-disable via shared lifecycle helper + reload/sync

5. Reuse shared lifecycle write helper
- Extract/centralize enabled-frontmatter mutation helper used by goal 2 (`workflow_run`) into shared module (e.g. `core/workflow/lifecycle.py`).
- Ensure both tool lifecycle ops and max-runs auto-disable call same safe path.
- Security parity requirement for shared helper:
  - `realpath` containment against workflow root
  - symlink escape rejection
  - atomic write/replace semantics

6a. Concurrency / transaction handling
- Implement counter increment + cap evaluation with transaction safety in persistent store.
- Ensure only one cap transition performs disable side effects when concurrent runs race at boundary.
- Keep event emission idempotent at cap boundary (single authoritative `max_runs_reached` transition event per reached state).

6. Emit clear stop/audit events
- Add event (proposal): `workflow_max_runs_reached`
- Minimum payload:
  - `workflow_id`
  - `max_runs`
  - `successful_run_count`
  - `stop_reason: "max_runs_reached"`
  - `enabled_before`, `enabled_after`

7. Docs update
- Update `docs/use/reference.md` frontmatter section:
  - add `max_runs`
  - define semantics and examples
  - clarify relationship to `enabled` and manual runs

8. Local smoke tests
- Fast targeted tests only:
  - config validation (`max_runs <= 0` rejected)
  - counter increment/persistence
  - cap transition toggles `enabled` and emits event

9. Handoff
- Request maintainer-run full validation and iterate on failures.

## Event Contract (Goal 3)

### Event: `workflow_max_runs_reached`
- Fires when successful run count reaches cap and auto-disable action is executed.
- Minimum payload keys:
  - `workflow_id`
  - `max_runs`
  - `successful_run_count`
  - `stop_reason` (`max_runs_reached`)
  - `enabled_before`
  - `enabled_after`

### Existing events
- Continue relying on `job_synced` / `job_removed` for scheduler outcomes.

## Open Questions to Lock Before Coding
- Should failed runs count toward cap? (Plan assumes no.)
- Should manual runs be blocked after cap, or only scheduled runs prevented? (Plan assumes scheduled-stop only, preserving existing enabled semantics.)

## Validation Execution Reminder
- Per project guidance, do **not** run `python validation/run_validation.py` in-agent.
- Maintainers run full validation and share results.
