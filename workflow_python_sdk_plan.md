## Workflow Python SDK Implementation Plan

### Status Snapshot
- Current branch: `feature/workflow_python_sdk`
- Work completed so far:
  - added `python_steps` engine loading hook to [core/workflow/loader.py](/app/core/workflow/loader.py)
  - created experimental core package under `core/workflow/python_steps/`
  - added thin compatibility shim at `workflow_engines/python_steps/workflow.py`
  - implemented Phase 1 style load-time parsing and validation events
  - implemented Phase 2 style typed compilation and semantic validation events
  - implemented an initial Phase 3 executor for the earlier multi-step / `run_root` design
  - added validation scenarios for loading and execution
- Important note:
  - the implementation currently reflects the earlier design (`step(...)`, `run_root`, explicit `run_step(...)`, multi-section workflow shape)
  - the plan below now reflects the newer and preferred MVP direction:
    - one executable Python block
    - declarative `Step` objects
    - one `Workflow` object
    - sequential `workflow.run()`
    - constrained top-level constants
    - `Workflow(instructions=...)`
- That means the next work session should be a controlled refactor, not a fresh start.

### Goal
- Add an experimental `python_steps` workflow engine that lives beside the existing `step` engine.
- Keep markdown as the canonical artifact.
- Re-express existing workflow primitives through a constrained Python SDK embedded in markdown code fences.
- Deliver in small, testable phases so each slice can be exercised before the next one lands.
- Keep the real implementation centered in `core/workflow`, with engine modules used only as compatibility entrypoints during the transition.

### Current Code Anchors
- Workflow discovery, frontmatter validation, and engine loading live in [core/workflow/loader.py](/app/core/workflow/loader.py) and [core/workflow/parser.py](/app/core/workflow/parser.py).
- Workflow metadata is represented by [core/workflow/definition.py](/app/core/workflow/definition.py).
- The only engine today is [workflow_engines/step/workflow.py](/app/workflow_engines/step/workflow.py).
- The current workflow adapter layer is [core/core_services.py](/app/core/core_services.py).
- Existing primitive surface is documented in [docs/use/reference.md](/app/docs/use/reference.md).
- Product sketch and target authoring shape live in [workflow_python_skd_sketch.md](/app/workflow_python_skd_sketch.md).

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
- Keep implementation aligned with existing directive processors instead of duplicating selector logic.
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
- Add `tools=...` support in the SDK, mapped onto existing tool binding/runtime behavior.
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

### Terminology Note
- Keep `step` as the author-facing unit across both engines.
- The current `step` engine remains sequential by convention.
- The new Python engine MVP should also remain sequential by default, but through a typed `Workflow` object rather than implicit markdown section ordering.

### Next Concrete Step
- Refactor the current experiment toward the simpler MVP:
  - one executable Python block
  - declarative `Step` objects
  - one `Workflow` object
  - `workflow.run()` as the primary execution path
  - constrained reusable constant bindings
  - explicit workflow-level system instructions

### Pickup Point For Next Session
1. Refactor the parser in `core/workflow/python_steps/` to accept:
   - one executable Python block
   - top-level constant bindings
   - `Step(...)` and `Workflow(...)` declarations
   - `workflow.run()` as the terminal executable call
2. Replace the current old-shape compiler with a sequential workflow compiler:
   - compile constants
   - compile named `Step` objects
   - compile one `Workflow` object with `instructions=` and `steps=[...]`
3. Replace the old executor entry semantics:
   - remove dependency on `run_root`
   - execute `workflow.run()` in declared order
   - keep `workflow.run_step("name")` only as a targeted helper
4. Align validation events and scenarios with the new shape:
   - update loading scenario expectations from `step_count` to single-block workflow semantics where needed
   - make the execution scenario the primary Phase 3 contract
5. After local smoke tests pass, stop and ask maintainers for full validation results.
