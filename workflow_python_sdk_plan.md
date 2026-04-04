## Workflow Python SDK Implementation Plan

### Status Snapshot
- Current branch: `feature/workflow_python_sdk`
- Current state:
  - `python_steps` MVP authoring shape is working:
    - one executable Python block
    - declarative `Step(...)`
    - one `Workflow(...)`
    - terminal `workflow.run()`
    - constrained top-level constants, including reusable SDK-bound targets like `File(...).replace()`
    - workflow-level `instructions=...`
  - shared authoring surface lives in [core/authoring/](/app/core/authoring):
    - canonical primitives in [core/authoring/primitives.py](/app/core/authoring/primitives.py)
    - contract/introspection in [core/authoring/introspection.py](/app/core/authoring/introspection.py)
    - compile-only service in [core/authoring/service.py](/app/core/authoring/service.py)
    - SDK-owned helper namespaces now include `date` and `path`, exposed through the authoring inspection API
  - authoring support is live:
    - `internal_api(endpoint="authoring_sdk")` exposes the full doc-backed contract
    - `internal_api(endpoint="workflow_load_errors")` exposes load failures
    - `workflow_run(operation="test", workflow_name="...")` gives file-backed compile-only testing
    - rescan UI surfaces workflow load failures
  - real file-first authoring has been proven with successful one-shot sample workflows and end-to-end runs using the chat agent.
  - input extraction is now in place:
    - shared typed input runtime lives in [core/workflow/input_resolution.py](/app/core/workflow/input_resolution.py)
    - `python_steps` input execution now builds typed requests directly and no longer serializes back into directive strings
    - `@input` is now a thin adapter in [core/directives/input.py](/app/core/directives/input.py): parse directive text, validate parameter syntax, delegate to shared runtime
    - shared prompt assembly is reused through [core/chunking/prompt_builder.py](/app/core/chunking/prompt_builder.py)
    - pending state updates in `python_steps` now follow the same success boundary as the string DSL
    - targeted selector validation passed for both a `python_steps` scenario and a cross-surface shared-runtime scenario
  - output extraction is now in place:
    - shared typed output runtime lives in [core/workflow/output_resolution.py](/app/core/workflow/output_resolution.py)
    - `python_steps` output execution now resolves typed file/variable targets through that shared runtime before writing
    - `@output` and `@header` are now thin adapters in [core/directives/output.py](/app/core/directives/output.py) and [core/directives/header.py](/app/core/directives/header.py)
    - input routing and tool output routing now use the same shared output target resolution
    - targeted static checks and local smoke probes passed, and a new shared-runtime output scenario was added for maintainer validation
  - tool extraction is now in place:
    - shared typed tool binding lives in [core/workflow/tool_binding.py](/app/core/workflow/tool_binding.py)
    - `@tools` in [core/directives/tools.py](/app/core/directives/tools.py) is now a thin adapter over that shared runtime
    - `python_steps` now accepts a narrow typed `tools=` step extra and resolves tool binding through the same shared runtime
    - tool routing wrappers now come from the shared runtime instead of directive-owned code
    - targeted validation passed for cross-surface tool-binding parity in [validation/scenarios/integration/core/tools_shared_runtime.py](/app/validation/scenarios/integration/core/tools_shared_runtime.py)
  - execution-prep extraction is now in place:
    - shared step execution preparation lives in [core/workflow/execution_prep.py](/app/core/workflow/execution_prep.py)
    - shared helpers now own:
      - model-execution resolution
      - run gating (`run_on`)
      - prompt assembly from resolved inputs
      - workflow/tool instruction-layer composition
    - both the string DSL engine and `python_steps` now use that shared execution-prep runtime
    - `python_steps` now supports narrow typed `run_on=...` step extras through the same shared gating semantics
    - targeted validation passed for cross-surface execution-prep parity in [validation/scenarios/integration/core/execution_prep_shared_runtime.py](/app/validation/scenarios/integration/core/execution_prep_shared_runtime.py)
  - image prompt parity is now explicitly validated:
    - cross-surface image coverage lives in [validation/scenarios/integration/core/image_shared_runtime.py](/app/validation/scenarios/integration/core/image_shared_runtime.py)
    - `python_step_prompt` now emits `attached_image_count` and `prompt_warnings`, matching the DSL prompt event shape more closely
    - `images=auto|ignore` behavior is now proven consistent across the string DSL and `python_steps`, including deduped embedded-image handling
  - richer SDK output shapes are now in place:
    - `File(...).new()` and `Var(...).new()` are supported in the authoring surface
    - `Step(..., outputs=[...])` is supported alongside the existing single-target `output=...` path
    - top-level constants can now hold lists of output targets for reuse in `outputs=[...]`
    - targeted validation passed in [validation/scenarios/integration/core/python_steps_output_shapes.py](/app/validation/scenarios/integration/core/python_steps_output_shapes.py)
  - target-level SDK headers are now in place:
    - `File(..., header="...")` now resolves through the shared header runtime in `python_steps`
    - targeted validation passed in [validation/scenarios/integration/core/python_steps_target_headers.py](/app/validation/scenarios/integration/core/python_steps_target_headers.py)
    - validation date control now applies consistently to both the legacy step engine and `python_steps`
  - SDK path expansion now follows the shared runtime path:
    - `python_steps` no longer pre-formats file paths locally before input/output resolution
    - SDK authoring now supports typed `date.*()` and `path.join(...)` helpers for dynamic paths
    - raw brace substitutions in `File(...)` path arguments are now rejected by the SDK compiler
    - targeted cross-surface validation passed in [validation/scenarios/integration/core/path_expansion_shared_runtime.py](/app/validation/scenarios/integration/core/path_expansion_shared_runtime.py)
    - broader date-pattern matrix coverage also passed in [validation/scenarios/integration/core/path_expansion_matrix_shared_runtime.py](/app/validation/scenarios/integration/core/path_expansion_matrix_shared_runtime.py)
    - current covered runtime behavior includes the full existing date-pattern set, now reached from typed SDK helpers rather than brace-style SDK paths
  - glob and special-path input parity now has explicit cross-surface coverage:
    - [validation/scenarios/integration/core/glob_shared_runtime.py](/app/validation/scenarios/integration/core/glob_shared_runtime.py)
    - covered behavior includes plain glob inputs and refs-only inputs for paths containing parentheses
    - glob strings remain a reasonable SDK surface; unlike brace substitutions, they are already a familiar Python-adjacent convention and do not create the same f-string ambiguity
  - representative custom format-token parity now has explicit cross-surface coverage:
    - [validation/scenarios/integration/core/format_token_shared_runtime.py](/app/validation/scenarios/integration/core/format_token_shared_runtime.py)
    - covered formatter behavior includes `YYMMDD`, `YYYY_MM_DD`, `ddd`, and `MMM`
  - buffer/routing parity is now reviewed more concretely:
    - cross-surface coverage lives in [validation/scenarios/integration/core/buffer_routing_shared_runtime.py](/app/validation/scenarios/integration/core/buffer_routing_shared_runtime.py)
    - verified behavior includes:
      - run/session-scoped variable reads and writes
      - routed input to variables
      - numbered routed variables via `write_mode=new`
    - remaining routing gap is mostly the workflow-context `output=context` question for the SDK surface
- Next phase:
  - keep using [workflow_python_sdk_parity_checklist.md](/app/workflow_python_sdk_parity_checklist.md) as the behavior target, but change the implementation strategy
  - continue extracting typed core workflow services that both authoring modes can call
  - highest-value next work is remaining authoring-contract decisions and execution coverage, especially:
    - broader routed-output execution
    - thinking/model-options shape
    - the `context` routing question
    - deciding whether header/date substitutions in SDK output metadata should also get a typed helper story
- Important implementation rule for the next phase:
  - avoid duplicating directive/workflow semantics inside `python_steps`
  - do not deepen the new SDK path's dependency on directive-string round-tripping
  - when parity work touches existing behavior like input selection, routing, write modes, variable scope, lifecycle actions, model setup, or tools, prefer extracting typed services under `core/workflow` (or nearby core runtime modules) that both the string DSL and the SDK can use
  - treat the Python authoring surface as the likely default future surface; the string DSL should trend toward a thinner adapter over shared typed runtime behavior
  - if reuse requires slowing down to refactor first, do that rather than adding a second drifting implementation
- Validation requirement for the next phase:
  - each parity slice should come with targeted validation or smoke coverage
  - maintainers still own the full validation suite, but new shared semantics should be exercised in scenarios that prove both the old workflow DSL and the SDK path still behave correctly
  - current shared-runtime validation anchors:
    - [validation/scenarios/integration/core/input_selector_shared_runtime.py](/app/validation/scenarios/integration/core/input_selector_shared_runtime.py)
    - [validation/scenarios/integration/core/output_shared_runtime.py](/app/validation/scenarios/integration/core/output_shared_runtime.py)
    - [validation/scenarios/integration/core/tools_shared_runtime.py](/app/validation/scenarios/integration/core/tools_shared_runtime.py)
    - [validation/scenarios/integration/core/execution_prep_shared_runtime.py](/app/validation/scenarios/integration/core/execution_prep_shared_runtime.py)
    - [validation/scenarios/integration/core/image_shared_runtime.py](/app/validation/scenarios/integration/core/image_shared_runtime.py)
    - [validation/scenarios/integration/core/python_steps_output_shapes.py](/app/validation/scenarios/integration/core/python_steps_output_shapes.py)
    - [validation/scenarios/integration/core/buffer_routing_shared_runtime.py](/app/validation/scenarios/integration/core/buffer_routing_shared_runtime.py)
    - [validation/scenarios/integration/core/python_steps_target_headers.py](/app/validation/scenarios/integration/core/python_steps_target_headers.py)
    - [validation/scenarios/integration/core/path_expansion_shared_runtime.py](/app/validation/scenarios/integration/core/path_expansion_shared_runtime.py)
    - [validation/scenarios/integration/core/path_expansion_matrix_shared_runtime.py](/app/validation/scenarios/integration/core/path_expansion_matrix_shared_runtime.py)
    - [validation/scenarios/integration/core/glob_shared_runtime.py](/app/validation/scenarios/integration/core/glob_shared_runtime.py)
    - [validation/scenarios/integration/core/format_token_shared_runtime.py](/app/validation/scenarios/integration/core/format_token_shared_runtime.py)
- Current limitation:
  - the authoring loop is working, but semantic parity is still incomplete, especially around selectors/stateful file processing, output/routing behavior, tool access, and broader directive coverage.
  - input resolution, output target resolution, tool binding, and step execution preparation are now shared, but several authoring-contract decisions and broader parity gaps remain open.

### Goal
- Add an experimental `python_steps` workflow engine that lives beside the existing `step` engine.
- Keep markdown as the canonical artifact.
- Re-express existing workflow primitives through a constrained Python SDK embedded in markdown code fences.
- Deliver in small, testable phases so each slice can be exercised before the next one lands.
- Keep the real implementation centered in `core/workflow`, with engine modules used only as compatibility entrypoints during the transition.
- Use typed workflow runtime services as the long-term source of behavior, with authoring-mode-specific parsing layered on top.

### Current Code Anchors
- Workflow discovery, frontmatter validation, and engine loading live in [core/workflow/loader.py](/app/core/workflow/loader.py) and [core/workflow/parser.py](/app/core/workflow/parser.py).
- Workflow metadata is represented by [core/workflow/definition.py](/app/core/workflow/definition.py).
- The only engine today is [workflow_engines/step/workflow.py](/app/workflow_engines/step/workflow.py).
- The current workflow adapter layer is [core/core_services.py](/app/core/core_services.py).
- Directive-owned runtime behavior currently lives mainly under [core/directives/](/app/core/directives), especially [core/directives/input.py](/app/core/directives/input.py), [core/directives/output.py](/app/core/directives/output.py), [core/directives/tools.py](/app/core/directives/tools.py), and [core/directives/header.py](/app/core/directives/header.py).
- Existing primitive surface is documented in [docs/use/reference.md](/app/docs/use/reference.md).
- Product sketch and target authoring shape live in [workflow_python_sdk_sketch.md](/app/workflow_python_sdk_sketch.md).

### Design Constraints
- `python_steps` must be additive. Existing `step` workflows must keep working unchanged.
- Python blocks are not arbitrary Python. The runtime should allow only approved SDK names and safe expression forms.
- The first SDK slice should be deliberately narrow, but the shape must accommodate existing workflow primitives from the reference doc.
- Validation should remain artifact-oriented and deterministic where possible.
- Keep `step` as the user-facing term in the SDK and docs. Python-authored steps may execute sequentially or via explicit composition, but the unit remains a step.
- New architecture should avoid deepening the long-term dependency on `workflow_engines/*` or `CoreServices`.
- The MVP should prioritize sequential workflow parity over branching or general orchestration.
- The workflow file should be as simple as possible: YAML frontmatter plus a single executable Python block.
- The MVP should allow limited top-level constant bindings for readability and reuse, but not arbitrary Python expressions.
- Workflow-level instructions remain important and should have an explicit place in the new format, rather than being lost inside per-step prompts.

### SDK Shape Principles
- Use typed SDK objects as the contract, not ad hoc dicts.
- Separate authoring primitives from execution internals:
  - authoring SDK: `Step`, `Workflow`, `File`, `Var`
  - internal IR: validated step list and workflow execution plan
- Separate parsing concerns from runtime behavior:
  - string DSL parses markdown directives into typed runtime requests
  - Python SDK compiles directly into typed runtime requests
  - shared runtime services execute those requests without needing to know which authoring surface produced them
- Put parser, compiler, and executor code under `core/workflow/python_steps/` so the new execution model is born in the core workflow layer rather than as a second monolithic engine.
- Keep `workflow_engines/python_steps/workflow.py` as a thin compatibility shim that delegates into the core implementation.
- Model current directive capabilities explicitly so the SDK can grow toward parity without redesign:
  - inputs: file and variable sources, selector options, refs-only, truncation, properties, routing
  - outputs: file and variable targets, scope, write mode
  - execution: model selection, tools, prompt, run gating
- Keep `Step` declarative. Orchestration belongs to `Workflow`, not to individual step definitions.
- Do not allow arbitrary Python control flow in workflow files. If richer orchestration is needed later, it should be introduced as constrained workflow-level API methods rather than open-ended Python.
- Permit constrained constant reuse such as:
  - `PROMPT_GATHER = "..."` then `prompt=PROMPT_GATHER`
  - `INSTRUCTIONS = "..."` then `Workflow(instructions=INSTRUCTIONS, ...)`
  - only for literal-safe top-level assignments validated statically
- Preserve workflow-level system instructions as a first-class concept via the workflow object itself:
  - canonical shape: `Workflow(instructions=..., steps=[...])`
  - the `instructions=` value may be inline or may reference a validated top-level constant
  - this should map onto the same runtime role as workflow-level instructions in the current engine
- Prefer typed runtime request/response models over string reconstruction:
  - avoid converting SDK objects into directive strings and reparsing them as a permanent design
  - if temporary bridging is needed for a parity slice, follow it with extraction into typed shared services before expanding adjacent behavior
- Prefer typed SDK helpers over DSL-era string mini-languages:
  - brace substitutions like `File("daily/{today}")` should not be used in the Python SDK path surface
  - the intended SDK direction is explicit typed helpers such as `date.today()` and `path.join(...)`
  - use custom SDK-owned helpers rather than stdlib lookalikes like `datetime`, `os.path`, or `pathlib.Path`
  - keep globs as plain strings; `File("notes/*")` is already familiar and does not carry the same ambiguity as brace substitutions

### SDK Date/Path Direction
- The string DSL keeps brace-based date substitutions because that is part of its established contract.
- The Python SDK should diverge here and use typed path/date composition instead.
- Target direction:
  - date helpers:
    - `date.today()`
    - `date.yesterday()`
    - `date.tomorrow()`
    - `date.this_week()`
    - `date.last_week()`
    - `date.next_week()`
    - `date.this_month()`
    - `date.last_month()`
    - `date.day_name()`
    - `date.month_name()`
  - optional formatting:
    - `date.today(fmt="YYYYMMDD")`
    - `date.month_name(fmt="MMM")`
  - path composition:
    - `path.join("daily", date.today())`
    - `path.join("weekly", date.this_week())`
- Reasons for the divergence:
  - avoids the f-string-like ambiguity of raw brace syntax inside Python strings
  - keeps the SDK inspectable and structurally validatable
  - gives LLMs a more explicit, Python-native contract to follow
  - preserves the same end semantics while making the authoring surface clearer
- Deliberate non-goal:
  - do not expose full stdlib-style `datetime` or `pathlib` behavior in the SDK
  - familiarity is useful, but the API should remain clearly SDK-owned and constrained
- Current implementation status:
  - `date.*()` and `path.join(...)` are implemented in the SDK/introspection surface
  - `File(...)` path arguments now accept plain strings, glob strings, and typed `path.join(...)` expressions
  - raw brace substitutions are rejected for SDK file paths to keep the Python contract distinct from the DSL
  - shared runtime semantics below the compiler remain unchanged

### Emerging Primitive Direction
- The current `Step(...)` shape still bundles several concerns together:
  - input gathering
  - LLM invocation
  - downstream routing/writing
- A promising next evolution is to separate content generation from sink behavior.
- Candidate direction:
  - `Generate(...)` produces content from model + prompt + inputs
  - `Write(...)` consumes generated content and writes it to a sink
  - `File(...)`, `Var(...)`, and eventually `Context(...)` remain destination primitives
  - `header=` would move off `File(...)` and onto `Write(...)`, since it is a property of a write operation rather than a path
- Example shape under discussion:
  - `draft = Generate(name="draft", model="sonnet", inputs=[...], prompt="...")`
  - `write_daily = Write(source=draft, target=File(path.join("daily", date.today())).replace(), header=...)`
- Why this is interesting:
  - gives a cleaner place for future branching and routing primitives
  - makes it easier to treat file/variable/context writes as sibling sink operations
  - reduces the conceptual weight currently carried by `Step(...)`
- Current recommendation:
  - keep `Step(...)` working as the stable surface for now
  - explore whether `Step(...)` should eventually become sugar over lower-level `Generate(...)` + `Write(...)` primitives

### Architectural Direction Update
- Treat `python_steps` as the strategic authoring surface for the experiment, not just a sidecar engine.
- Evolve the runtime so core workflow behavior lives in typed services below both authoring modes.
- Make the string DSL progressively thinner:
  - parse directive text
  - map it into typed runtime requests
  - delegate execution to shared services
- Make the SDK path progressively more direct:
  - compile authoring primitives into typed runtime requests
  - execute those requests without directive-string round-tripping
  - where the DSL uses embedded string syntax, prefer Python-native typed helpers rather than copying the string syntax into the SDK unchanged
- Use this sequence for refactors:
  1. extract typed shared service
  2. move SDK to that service
  3. move string DSL to the same service
  4. delete obsolete directive-owned runtime logic

### Shared Runtime Extraction Targets
- Input resolution service
  - file and variable inputs
  - selector validation and defaults
  - pattern expansion and glob resolution
  - `pending` state metadata
  - truncation, refs-only, properties, image policy
  - required-input skip semantics
  - status: extracted and in active use by both `@input` and `python_steps`
- Output/routing service
  - file and variable targets
  - write modes
  - scope
  - header handling
  - routed input/output manifests
  - status: extracted for target resolution and header rendering; low-level writing remains in [core/utils/routing.py](/app/core/utils/routing.py), while broader parity decisions like multi-output and first-class `new` authoring are still open
- Tool binding service
  - tool selection and validation
  - routing allowances and output handling
  - workflow lifecycle tool integration
  - status: extracted and in active use by both `@tools` and `python_steps`
- Step execution preparation service
  - model execution resolution
  - prompt/input chunk assembly
  - workflow-level instruction composition
  - status: extracted and in active use by both the string DSL engine and `python_steps`

### Non-Goals For Initial Delivery
- No arbitrary imports or user-defined helper functions.
- No complete parity with every current directive in phase 1.
- No migration of existing `step` workflows.
- No attempt to unify workflows and context templates yet.
- No branching API in the MVP authoring shape.
- No multi-block executable structure in the MVP authoring shape.
- No arbitrary computed variables, helper functions, lambdas, or expression-based prompt assembly in the MVP.

### Phase Plan

#### Phase 1: Engine Skeleton And Safe Markdown Extraction
- Introduce the real implementation under `core/workflow/python_steps/`.
- Add a thin compatibility entrypoint at `workflow_engines/python_steps/workflow.py`.
- Keep current workflow loading unchanged except for recognizing `workflow_engine: python_steps`.
- Implement markdown parsing for a single executable Python block in the workflow body.
- Reject:
  - missing executable block
  - multiple executable Python blocks
  - unsupported top-level structure outside the supported note text + one code block shape
- Add a minimal AST validator that allows only:
  - simple assignment statements for named step/workflow declarations
  - simple assignment statements for literal-safe reusable constants
  - calls into approved SDK names
  - literals, lists, keyword args, simple names
- Do not execute tasks yet. Only load, parse, and validate structure.

Validation target:
- Local smoke test proves a `python_steps` workflow can be loaded.
- Invalid code fences or unsupported syntax fail with template-facing pointers.
- Add a validation scenario for workflow load success/failure at the compatibility shim boundary.

Progress:
- Partially complete under the earlier design.
- Loader hook, shim, parse-failure events, and load scenario exist today.
- Needs refactor to the new single-block `Step`/`Workflow` shape.

Decision-boundary events:
- `python_steps_blocks_parsed`
  - payload: `workflow_id`, `block_count`
- `python_steps_parse_failed`
  - payload: `workflow_id`, `phase`, `error`

#### Phase 2: Typed SDK And Compilation To Internal Step Definitions
- Add SDK models for:
  - `StepDefinition`
  - `WorkflowDefinition` for the python-authored workflow body
  - input sources: `FileInput`, `VarInput`
  - output targets: `FileTarget`, `VarTarget`
  - minimal execution-plan shape for sequential runs
- Implement approved SDK callables that construct these objects when evaluated in a restricted namespace.
- Compile the Python block into:
  - validated top-level constant bindings
  - named step declarations
  - one workflow declaration
  - a validated ordered step list for `workflow.run()`
- Add semantic validation:
  - unique step names
  - exactly one workflow object
  - workflow step list references only declared steps
  - referenced constants exist and are literal-safe
  - prompt-step shape validation for inputs, outputs, and model settings
  - workflow-level instructions resolve from `Workflow(instructions=...)`

Validation target:
- Local smoke tests compile a simple two-step workflow into deterministic step objects.
- Invalid workflow step references and duplicate names fail before execution.
- Extend validation scenario to assert step/workflow compilation behavior.

Progress:
- Partially complete under the earlier design.
- Typed models and compile-time semantic validation exist today.
- Needs redesign from the old operation graph shape to the new:
  - `Step`
  - `Workflow`
  - constant-binding aware single-block compilation

Decision-boundary events:
- `python_steps_compiled`
  - payload: `workflow_id`, `step_names`
- `python_steps_semantic_validation_failed`
  - payload: `workflow_id`, `step_name`, `error`

#### Phase 3: Minimal Executable Slice
- Execute the smallest useful subset:
  - `Step(... prompt=...)`
  - `model=...`
  - `inputs=[File(...), Var(...)]`
  - `output=File(...)` and `output=Var(...)`
  - `Workflow(instructions=..., steps=[...])`
  - top-level literal constants referenced by steps/workflow
  - workflow-level system instructions
  - `workflow.run()` for sequential execution in declared order
  - `workflow.run_step("name")` as a targeted execution helper
- Reuse existing runtime behavior where possible instead of inventing a second routing system:
  - file writing through existing output utilities
  - variable/buffer handling through existing runtime buffer/state abstractions
  - model resolution through existing model selection logic
- Introduce Python-step execution context types in `core/workflow` directly rather than routing new behavior through `CoreServices`.
- Define execution semantics around the workflow object, not a `run_root` step.

Validation target:
- New integration scenario executes a minimal deterministic `python_steps` workflow end-to-end.
- Artifacts assert:
  - output file written correctly
  - variable output available to downstream step
  - workflow steps execute in declared sequential order

Progress:
- Partially complete under the earlier design.
- Minimal execution exists today, but for the old `run_root` / `run_step` / `branch` shape.
- Execution scenario file has already been updated to the new desired sequential `Workflow(...).run()` authoring form.
- Executor/compiler/parser still need to be refactored to match that scenario shape.

Decision-boundary events:
- `python_step_started`
  - payload: `workflow_id`, `step_name`, `step_type`
- `python_step_completed`
  - payload: `workflow_id`, `step_name`
- `python_workflow_started`
  - payload: `workflow_id`, `step_names`
- `python_workflow_completed`
  - payload: `workflow_id`, `step_count`

#### Phase 4: Input/Output Parity Slice
- Expand `File(...)` and `Var(...)` to cover the highest-value directive parity from [docs/use/reference.md](/app/docs/use/reference.md):
  - file selectors: `pending`, `latest`, `limit`, `order`, `dir`
  - routing and write mode
  - `scope`
  - `required`, `refs_only`, `head`, `tail`, `properties`
- Typed shared input-resolution service is now extracted into [core/workflow/input_resolution.py](/app/core/workflow/input_resolution.py).
- `python_steps` input execution and string-DSL `@input` now both use that shared service.
- Next part of this phase is output/routing extraction so the same convergence happens for writes and routing manifests.
- Normalize SDK naming to stay Pythonic while preserving capability coverage.

Validation target:
- Focused smoke tests for selector and routing edge cases.
- Scenario assertions cover at least one selector mode, one routed variable output, and one required-input skip path.

Decision-boundary events:
- `python_inputs_resolved`
  - payload: `workflow_id`, `step_name`, `input_count`, `source_types`
- `python_input_resolution_failed`
  - payload: `workflow_id`, `step_name`, `error`

#### Phase 5: Tools And Advanced Composition
- Add `tools=...` support in the SDK via a typed shared tool-binding/runtime service rather than direct reuse of `@tools` string parsing as the long-term model.
- Only after the sequential model is stable, evaluate whether workflow-level orchestration helpers are needed:
  - `workflow.run_step_if(...)`
  - `workflow.write_if(...)`
  - other constrained `Workflow` methods
- Do not introduce arbitrary lambdas or open-ended Python control flow without a separate safety review.

Validation target:
- Targeted scenario proves one tool-enabled sequential workflow path.
- Failures remain template-facing and deterministic.

#### Phase 6: Authoring Support And Documentation
- Add developer docs for the `python_tasks` engine and the first supported SDK surface.
- Add developer docs for the `python_steps` engine and the first supported SDK surface.
- Document unsupported primitives explicitly.
- Add examples that parallel existing workflow patterns so maintainers can compare `step` and `python_tasks` forms.
- Consider an SDK inspection surface only after the SDK contract is stable enough to expose.

Validation target:
- Documentation examples remain loadable by smoke tests.
- Maintainers can run full validation and compare engine behavior.

#### Phase 7: Runtime Consolidation If The Experiment Proves Out
- Move from "new engine added" to "core workflow model has expanded".
- Refactor shared workflow concerns into `core/workflow` so old and new execution paths use more of the same runtime primitives.
- Reduce the engine layer to dispatch-only or remove it entirely if the loader/executor contract can be simplified safely.
- Identify `CoreServices` responsibilities that should move into explicit core workflow/runtime interfaces.
- Deprecate `CoreServices` once equivalent core interfaces exist and the old `step` path no longer depends on it materially.

Validation target:
- Old `step` workflows still load and execute after shared-runtime extraction.
- `python_steps` workflows continue to pass their existing scenario contracts.

### Immediate Next Implementation Steps
1. Extract a typed output/routing service under `core/workflow` or an adjacent core runtime module.
2. Define typed request/response models for file and variable output handling, including write modes, scope, manifests, and header behavior boundaries.
3. Move `python_steps` output execution to that typed service.
4. Adapt string-DSL output handling (`@output`, `@write_mode`, and likely `@header`) so parsing stays local, but execution delegates into the same typed service.
5. Extend validation so one scenario proves both the SDK and string DSL still behave identically for routed/written outputs after the extraction.

### Validation Target For The Refactor
- Extend [validation/scenarios/integration/core/python_steps_selector_parity.py](/app/validation/scenarios/integration/core/python_steps_selector_parity.py) as the SDK-side contract.
- Use [validation/scenarios/integration/core/input_selector_shared_runtime.py](/app/validation/scenarios/integration/core/input_selector_shared_runtime.py) as the cross-surface selector contract.
- Add or extend a cross-surface output/routing scenario once output extraction begins.
- Keep local smoke coverage for regex/date selector edge cases and pending state transitions.

### Risks And Contract-Sensitive Areas
- Persisted runtime state:
  - `pending` processing state in `/app/system` / validation system roots must remain compatible during refactors.
- Validation event compatibility:
  - existing selector and workflow events should remain stable unless there is a deliberate contract update.
- Frontmatter and runtime defaults:
  - `week_start_day` and date-pattern behavior must not drift between authoring modes.
- Tooling and routing:
  - input/output routing semantics interact with buffer scope and tool output behavior, so extraction order matters.

### Next Phase
- Move to Feature Development with the next extraction target: typed shared output/routing resolution.
- Maintainers can compare pre/post consolidation validation results before engine collapse is finalized.

### Recommended Execution Order
1. Phase 1: parsing and safe structure only
2. Phase 2: typed SDK and semantic compilation
3. Phase 3: minimal execution path
4. Phase 4: parity expansion for IO/routing
5. Phase 5: tools and richer composition
6. Phase 6: docs and authoring support
7. Phase 7: runtime consolidation and engine collapse, only if the experiment earns it

### Validation Strategy
- Agents should rely on local smoke tests for parser/compiler/executor slices.
- Add or extend validation scenarios as the executable contract for each phase.
- Ask maintainers to run full validation after each merged phase rather than waiting until the end.

### Risks To Watch
- Letting the SDK evaluator become a disguised general Python runner.
- Re-implementing selector/routing logic instead of reusing existing primitives.
- Mixing authoring concerns with execution details too early.
- Starting with too much parity and making the compiler/executor hard to reason about.
- Trying to collapse engines before the Python-step path has proven its value and execution shape.
- Allowing “just a little” extra Python until constant bindings quietly turn into general expression evaluation.
- Leaving the SDK surface implicit in parser/compiler internals, which forces LLM authoring back onto prose docs and code spelunking.
- Making authors validate workflows only through the full workflow runtime instead of a narrow sandbox loop with precise diagnostics.

### Authoring-Loop Assessment
- Current structure supports:
  - deterministic parse/compile validation for stored workflow files
  - deterministic minimal execution for checked-in workflows
- Current structure does not yet support the full LLM-authoring goal:
  - there is no canonical inspectable SDK module with real `Step` / `Workflow` / `File` / `Var` objects, signatures, and docstrings
  - the accepted contract is split across parser allowlists and compiler branches
  - there is no dedicated “compile this draft and sandbox-run it” service/tool for candidate workflow text
  - diagnostics are workflow-engine oriented, not shaped as a tight authoring/repair loop API

### Planning Conclusion
- The current structure is a good execution core, but not yet enough for direct SDK inspection plus sandbox trial runs.
- Before broad parity expansion, the architecture should add an explicit SDK contract and a narrow authoring sandbox boundary.
- The first extraction step is now complete:
  - canonical primitives live in [core/authoring/primitives.py](/app/core/authoring/primitives.py)
  - SDK introspection lives in [core/authoring/introspection.py](/app/core/authoring/introspection.py)
  - `python_steps` parser/compiler now consume authoring metadata from that shared module
- Remaining work is to move from “inspectable package exists” to “authoring sandbox and shared semantics exist”.

### Terminology Note
- Keep `step` as the author-facing unit across both engines.
- The current `step` engine remains sequential by convention.
- The new Python engine MVP should also remain sequential by default, but through a typed `Workflow` object rather than implicit markdown section ordering.

### Next Concrete Step
- Define the inspectable SDK contract and authoring sandbox boundary before continuing broad parity work:
  - keep moving parser/compiler/runtime assumptions onto `core/authoring`
  - add a sandbox compile/run path for candidate workflows
  - start extracting shared semantics below both directives and SDK adapters

### Pickup Point For Next Session
1. Continue moving the authoring contract into [core/authoring/](/app/core/authoring):
   - keep `Step`, `Workflow`, `File`, and `Var` as the canonical inspectable primitives
   - add explicit metadata for supported options, not just primitive/method names
2. Refactor `python_steps` parser/compiler further so they derive constructor and option support from `core/authoring` wherever practical.
3. Add a narrow authoring sandbox path that can:
   - compile candidate workflow markdown or Python-block text without registering a workflow
   - run it against a temp vault/temp runtime state using `model="test"`
   - return structured parse/compile/runtime diagnostics for iterative repair
4. Start extracting shared semantic services from directive-owned implementations:
   - input selection
   - output target normalization
   - write-mode handling
5. After that authoring loop and shared-semantic path exist, continue Phase 4 parity work on selectors/routing through the new contract.
