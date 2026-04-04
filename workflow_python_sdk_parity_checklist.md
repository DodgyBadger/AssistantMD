# Workflow Python SDK Parity Checklist

Reference baseline: [docs/use/reference.md](/app/docs/use/reference.md)

Purpose: track remaining work to bring file-first workflow authoring closer to parity with the existing workflow surface, while keeping the Python SDK constrained and inspectable.

## Current Read

- The authoring loop is working:
  - inspect via `internal_api(endpoint="authoring_sdk")`
  - write real workflow files under `AssistantMD/Workflows/`
  - compile-check via `workflow_run(operation="test", workflow_name="...")`
  - execute via `workflow_run(operation="run", ...)`
- The biggest remaining gaps are semantic parity, not basic authoring shape.
- Priority is to close the highest-value workflow gaps first, especially stateful file processing and tool access.

## Highest Priority

- [ ] `File(..., pending=True)` parity
  - Goal: make pending file selection reliable for incremental processing workflows.
  - Needed behavior:
    - selector returns the next unprocessed file deterministically
    - processed state is updated only after successful step completion
    - `limit`, `order`, and `dir` work consistently with `pending`
  - Why first: unlocks workflows like “process next unread image every 5 minutes” without custom state tracking.

- [ ] `latest`, `limit`, `order`, `dir` parity for file selectors
  - Goal: reuse the current selector semantics from directive workflows.
  - Needed behavior:
    - `latest=True`
    - `limit=N`
    - `order=mtime|ctime|alphanum|filename_dt`
    - `dir=asc|desc`
    - `dt_pattern` and `dt_format` when `order=filename_dt`

- [ ] Step-level tool access
  - Goal: let authored workflows declare tool usage explicitly.
  - Needed behavior:
    - typed equivalent of `@tools`
    - path for lifecycle actions like `workflow_run`
    - authoring docs and inspection metadata updated accordingly
  - Why high priority: enables workflows to disable themselves, inspect state, and perform non-LLM step actions cleanly.

## Input / Output Parity

- [ ] `required` input behavior
  - Clarify and implement real runtime behavior for missing inputs.
  - Current reference wording says “Skip the step when no matching input is found.”
  - Need deterministic skip/failure semantics and observability.

- [ ] `refs_only` input mode
  - File and variable refs should be passable without full inline content.

- [ ] `head` / `tail`
  - Current SDK accepts these options in metadata.
  - Need runtime behavior parity with directive workflows.

- [ ] `properties`
  - Support frontmatter-only reads and keyed property selection.

- [ ] `images=auto|ignore`
  - Important for image workflows.
  - Need clear parity with current file-input image handling.

- [ ] `output=...` on inputs
  - Directive workflows can route resolved input immediately.
  - Decide whether Python SDK should support this directly or through a different typed shape.

- [ ] `write_mode` parity
  - Existing target methods cover `append` and `replace`.
  - Need a typed story for `new`.

- [ ] Multiple outputs
  - Current directives allow multiple `@output` lines.
  - Current SDK supports only one `output`.
  - Decide whether parity requires `outputs=[...]` or another explicit multi-target shape.

- [ ] Variable scope parity
  - `scope=run|session` for `Var(...)`
  - both reading and writing behavior need to match current buffer semantics.

## Execution Controls

- [ ] `model="none"` parity
  - Needed for non-LLM transformation or pure routing steps.
  - Current docs/reference support it in directive workflows.

- [ ] Thinking / model options
  - Decide whether these belong in typed `Step(...)` metadata now or later.

- [ ] Step run gating (`@run_on`)
  - Need a typed equivalent for day-limited step execution.

- [ ] `@header` parity
  - Decide whether file heading injection should be a target option, step option, or explicit helper.

- [ ] Caching (`@cache`)
  - Lower priority, but should be tracked explicitly.

- [ ] Recent-run context (`@recent_runs`, `@recent_summaries`)
  - Decide whether these are workflow-only features, context features, or should have typed equivalents.

## Frontmatter Parity

- [x] `workflow_engine`
- [x] `schedule`
- [x] `enabled`
- [x] `description`
- [ ] `week_start_day`
  - Needed if date-pattern behavior should match current workflow semantics.
- [ ] custom-field behavior
  - Likely already acceptable, but should be verified for `python_steps` workflows.

## Patterns / Path Expansion

- [ ] Date-pattern parity for file paths
  - `{today}`
  - `{yesterday}`
  - `{tomorrow}`
  - `{this-week}`
  - `{last-week}`
  - `{next-week}`
  - `{this-month}`
  - `{last-month}`
  - `{day-name}`
  - `{month-name}`

- [ ] Glob parity
  - Ensure path expansion matches directive workflows before selector pipeline runs.

- [ ] Format token parity
  - Needed for more advanced filename/date workflows.

## Buffer / Routing Parity

- [ ] Buffer behavior review
  - Confirm `Var(...)` maps correctly onto existing run/session buffer semantics.

- [ ] Routing parity
  - Existing routing concepts in reference:
    - `file:`
    - `variable:`
    - `context`
  - Need to decide which of these belong in workflow SDK v1 and which remain context-only.

## Authoring / UX

- [x] Full inspectable contract endpoint
- [x] File-first compile-only testing path for chat
- [x] Rescan surfacing for failed workflow loads
- [ ] Stronger default-tool/use sequencing
  - The model can still skip contract inspection if examples seem sufficient.
  - Continue tuning prompts/templates around:
    - inspect
    - write file
    - test
    - run

- [ ] More sample workflows
  - Build a small suite of representative workflows:
    - weekly planner
    - incremental image indexer
    - selector-heavy file batch
    - tool-using lifecycle workflow

## Suggested Implementation Order

1. `pending` semantics and selector parity
2. Step-level tools
3. `required`, `refs_only`, `head` / `tail`, `properties`, image handling
4. multi-output and `new` write mode decisions
5. run gating, header, and lower-priority execution controls
6. broader pattern and buffer/routing parity review
