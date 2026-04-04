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
- Input runtime extraction is now in place:
  - shared typed input resolution lives in [core/workflow/input_resolution.py](/app/core/workflow/input_resolution.py)
  - `@input` now parses directive text and delegates into that shared runtime
  - `python_steps` input execution now builds typed requests directly instead of serializing back into directive strings
  - selector parity is now covered by:
    - [validation/scenarios/integration/core/python_steps_selector_parity.py](/app/validation/scenarios/integration/core/python_steps_selector_parity.py)
    - [validation/scenarios/integration/core/input_selector_shared_runtime.py](/app/validation/scenarios/integration/core/input_selector_shared_runtime.py)
- Output runtime extraction is now in place:
  - shared typed output resolution lives in [core/workflow/output_resolution.py](/app/core/workflow/output_resolution.py)
  - `@output` and `@header` now delegate into that shared runtime
  - `python_steps` output execution now resolves typed file/variable targets through that same runtime
  - input routing and tool routing now reuse the same output target resolution
  - maintainer validation still needs to run:
    - [validation/scenarios/integration/core/output_shared_runtime.py](/app/validation/scenarios/integration/core/output_shared_runtime.py)
- Tool runtime extraction is now in place:
  - shared typed tool binding lives in [core/workflow/tool_binding.py](/app/core/workflow/tool_binding.py)
  - `@tools` now delegates into that shared runtime
  - `python_steps` now supports a narrow `tools=` step extra resolved through the same runtime
  - targeted cross-surface validation passed in:
    - [validation/scenarios/integration/core/tools_shared_runtime.py](/app/validation/scenarios/integration/core/tools_shared_runtime.py)
- Execution-prep extraction is now in place:
  - shared step execution preparation lives in [core/workflow/execution_prep.py](/app/core/workflow/execution_prep.py)
  - shared runtime now owns model-execution resolution, run gating, prompt assembly, and instruction-layer composition
  - `python_steps` now supports narrow `run_on=...` step extras through the same shared gating semantics
  - targeted cross-surface validation passed in:
    - [validation/scenarios/integration/core/execution_prep_shared_runtime.py](/app/validation/scenarios/integration/core/execution_prep_shared_runtime.py)
- SDK authoring direction is now intentionally diverging from the DSL for date substitutions:
  - the string DSL keeps brace patterns like `{today}`
  - the Python SDK now uses typed `date.*()` and `path.join(...)` helpers instead of embedding brace syntax inside strings
  - globs remain acceptable as plain strings in the SDK, e.g. `File("notes/*")`

## Highest Priority

- [x] `File(..., pending=True)` parity
  - Goal: make pending file selection reliable for incremental processing workflows.
  - Delivered behavior:
    - selector returns the next unprocessed file deterministically
    - processed state is updated only after successful step completion
    - `limit`, `order`, and `dir` work consistently with `pending`
  - Implementation note:
    - behavior now comes from shared typed input resolution, not SDK-to-directive string round-tripping

- [x] `latest`, `limit`, `order`, `dir` parity for file selectors
  - Goal: reuse the current selector semantics from directive workflows.
  - Delivered behavior:
    - `latest=True`
    - `limit=N`
    - `order=mtime|ctime|alphanum|filename_dt`
    - `dir=asc|desc`
    - `dt_pattern` and `dt_format` when `order=filename_dt`

- [x] Step-level tool access
  - Goal: let authored workflows declare tool usage explicitly.
  - Delivered behavior:
    - shared typed tool binding is used by both `@tools` and `python_steps`
    - `python_steps` supports a narrow typed `tools=` step extra
    - lifecycle tools like `workflow_run` resolve through the same shared path
  - Follow-up:
    - broaden validation from resolution parity into routed tool execution examples

## Input / Output Parity

- [x] `required` input behavior
  - Clarify and implement real runtime behavior for missing inputs.
  - Current behavior:
    - missing required file/variable input resolves to a deterministic skip signal
    - `python_steps` now honors that skip signal through the shared input runtime

- [x] `refs_only` input mode
  - File and variable refs should be passable without full inline content.

- [x] `head` / `tail`
  - Current SDK accepts these options in metadata.
  - Runtime behavior now comes from the shared typed input service.

- [x] `properties`
  - Support frontmatter-only reads and keyed property selection.

- [x] `images=auto|ignore`
  - Important for image workflows.
  - Shared input/prompt runtime now has explicit cross-surface validation in:
    - [validation/scenarios/integration/core/image_shared_runtime.py](/app/validation/scenarios/integration/core/image_shared_runtime.py)
  - Covered behavior:
    - direct image inputs
    - embedded markdown images
    - `images="ignore"`
    - deduped identical-image handling

- [ ] `output=...` on inputs
  - Directive workflows can route resolved input immediately.
  - Decide whether Python SDK should support this directly or through a different typed shape.

- [x] `write_mode` parity
  - Shared runtime now normalizes and executes write modes for both authoring surfaces.
  - SDK authoring now supports:
    - `.append()`
    - `.replace()`
    - `.new()`

- [x] Multiple outputs
  - Current directives allow multiple `@output` lines.
  - SDK now supports `outputs=[...]` while keeping `output=...` as the single-target convenience path.
  - Targeted coverage lives in:
    - [validation/scenarios/integration/core/python_steps_output_shapes.py](/app/validation/scenarios/integration/core/python_steps_output_shapes.py)

- [x] Variable scope parity
  - `scope=run|session` for `Var(...)`
  - read-side support exists in shared input resolution
  - write-side support now routes through shared output resolution
  - cross-surface coverage now lives in:
    - [validation/scenarios/integration/core/buffer_routing_shared_runtime.py](/app/validation/scenarios/integration/core/buffer_routing_shared_runtime.py)

## Execution Controls

- [x] `model="none"` parity
  - Needed for non-LLM transformation or pure routing steps.
  - Shared execution-prep runtime now applies the same skip semantics to both authoring surfaces.

- [ ] Thinking / model options
  - Decide whether these belong in typed `Step(...)` metadata now or later.

- [x] Step run gating (`@run_on`)
  - Shared execution-prep runtime now applies the same run gating semantics to both authoring surfaces.
  - `python_steps` supports a narrow typed `run_on=...` step extra.

- [x] `@header` parity
  - Shared header rendering is extracted in [core/workflow/output_resolution.py](/app/core/workflow/output_resolution.py).
  - SDK authoring now supports target-level headers via `File(..., header="...")`.
  - Targeted validation passed in:
    - [validation/scenarios/integration/core/python_steps_target_headers.py](/app/validation/scenarios/integration/core/python_steps_target_headers.py)
  - Validation note:
    - the validation harness now applies test-date overrides to both the legacy step engine and `python_steps`, so header/date-pattern checks are aligned across surfaces.

- [ ] Caching (`@cache`)
  - Lower priority, but should be tracked explicitly.

- [ ] Recent-run context (`@recent_runs`, `@recent_summaries`)
  - Decide whether these are workflow-only features, context features, or should have typed equivalents.

## Frontmatter Parity

- [x] `workflow_engine`
- [x] `schedule`
- [x] `enabled`
- [x] `description`
- [x] `week_start_day`
  - `python_steps` executor threads `week_start_day` into shared input and output/header resolution.
  - Explicit validation now exists through:
    - [validation/scenarios/integration/core/python_steps_target_headers.py](/app/validation/scenarios/integration/core/python_steps_target_headers.py)
- [ ] custom-field behavior
  - Likely already acceptable, but should be verified for `python_steps` workflows.

## Patterns / Path Expansion

- [x] Date-pattern runtime parity for file paths
  - string DSL and current SDK runtime path resolution both flow through the shared runtime path instead of SDK-local formatting
  - targeted cross-surface validation passed in:
    - [validation/scenarios/integration/core/path_expansion_shared_runtime.py](/app/validation/scenarios/integration/core/path_expansion_shared_runtime.py)
    - [validation/scenarios/integration/core/path_expansion_matrix_shared_runtime.py](/app/validation/scenarios/integration/core/path_expansion_matrix_shared_runtime.py)
  - covered explicitly:
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
    - `{today:YYYYMMDD}`
  - note:
    - this item is about runtime semantics, not the final preferred SDK syntax

- [x] Typed SDK date/path authoring
  - SDK now supports:
    - `path.join("daily", date.today())`
    - `path.join("weekly", date.this_week())`
    - `path.join("plans", date.month_name(fmt="MMM"))`
  - Constraints implemented:
    - helpers are SDK-owned, not stdlib `datetime`, `os.path`, or `pathlib`
    - helper metadata is exposed through the authoring inspection API
    - typed helpers compile into the same shared runtime semantics already validated above
  - Contract enforcement:
    - raw brace substitutions are now rejected for SDK `File(...)` path arguments
  - Validation:
    - [validation/scenarios/integration/core/python_steps_loading.py](/app/validation/scenarios/integration/core/python_steps_loading.py)
    - [validation/scenarios/integration/core/path_expansion_shared_runtime.py](/app/validation/scenarios/integration/core/path_expansion_shared_runtime.py)
    - [validation/scenarios/integration/core/path_expansion_matrix_shared_runtime.py](/app/validation/scenarios/integration/core/path_expansion_matrix_shared_runtime.py)
    - [validation/scenarios/integration/core/format_token_shared_runtime.py](/app/validation/scenarios/integration/core/format_token_shared_runtime.py)

- [x] Glob parity
  - Shared input runtime owns glob/path expansion for both authoring surfaces.
  - Explicit cross-surface validation now exists in:
    - [validation/scenarios/integration/core/glob_shared_runtime.py](/app/validation/scenarios/integration/core/glob_shared_runtime.py)
  - Covered behavior includes:
    - plain glob inputs
    - refs-only special paths containing parentheses
  - Authoring decision:
    - keep globs as plain strings in the SDK

- [x] Format token parity
  - Shared formatter behavior now has explicit cross-surface validation in:
    - [validation/scenarios/integration/core/format_token_shared_runtime.py](/app/validation/scenarios/integration/core/format_token_shared_runtime.py)
  - Covered representative tokens:
    - `YYMMDD`
    - `YYYY_MM_DD`
    - `ddd`
    - `MMM`

## Buffer / Routing Parity

- [x] Buffer behavior review
  - `Var(...)` now has explicit cross-surface coverage for run/session buffer semantics.
  - Shared output resolution now owns buffer target scope handling.

- [ ] Routing parity
  - Existing routing concepts in reference:
    - `file:`
    - `variable:`
    - `context`
  - read-side input routing behavior exists in shared input runtime
  - write-side target resolution now comes from shared output runtime
  - cross-surface coverage now proves `file:` and `variable:`-style buffer routing behavior for the SDK path
  - keep open mainly for `context` routing review and broader routed-manifest coverage

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

1. thinking/model-options authoring decision
2. broader routed-output execution coverage
3. `context` routing decision for the SDK surface
4. decide whether SDK header substitutions should also move to typed helpers
