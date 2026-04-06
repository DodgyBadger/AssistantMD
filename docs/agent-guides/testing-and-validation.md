# Testing and Validation

## Validation Scope
- Primary integration testing is scenario validation under `validation/scenarios/`.
- Prefer adding or adjusting scenario files by feature area (for example, `validation/scenarios/integration/`).
- Scenario names should be descriptive and behavior-oriented (for example, `context_manager_cache_modes.py`).

## Validation-First Workflow

Use the validation framework to shape feature design from day one, not as a final verification pass.

### 1) Write the feature spec in terms of artifacts
- final artifacts users will observe (files, API responses, state changes)
- internal artifacts required for confidence (validation events at key decision points)
- non-negotiable invariants (what must never regress)

### 2) Add scenario assertions before implementation
- create or extend a scenario with failing assertions for those artifacts
- include final artifact assertions (end-user behavior)
- include internal artifact assertions (decision correctness, skip reasons, routing, cache behavior)

This makes the scenario the executable contract for the feature.

### 3) Define event contracts in the implementation plan
- event name
- minimum payload keys that represent behavior
- when the event should fire

Only add events at decision boundaries; avoid noisy instrumentation.

### 4) Implement in small slices until scenario contract passes
- build the smallest increment that satisfies the next failing assertion
- keep assertions behavior-focused (avoid coupling to internals)
- prefer deterministic scenarios (`@model test`) unless real model behavior is explicitly required
- do not assert on free-form LLM wording; assert on validation events you control, exact API/file artifacts, and other deterministic outputs instead

### 5) Tighten and keep
- keep contract assertions as long-term regression guards
- remove temporary debug-only events/assertions
- preserve stable event names/payload keys as compatibility surface for scenarios

## What Matters Now
- Assert behavior, not implementation accidents.
- Prefer deterministic scenarios (`@model test`) unless real model behavior is essential.
- Use local smoke tests to probe exact edge cases quickly, especially for helper functions and failure paths.
- Ask maintainers for full validation results instead of running the suite yourself.

## Definition of Done (Workflow Perspective)
- New behavior is represented by scenario assertions (new or updated).
- Decision-heavy branches have stable, behavior-oriented validation events when needed.
- Temporary debug instrumentation is removed.
- Relevant technical docs are updated (architecture, usage, or examples).

## Execution Rules
- Agents should run individual scenarios directly to validate functionality being built.
- Only the maintainers should run the full validation suite.
- In this dev container, avoid long validation jobs unless explicitly requested.

## Agent Smoke Tests (Local, Fast)
- For new functions/modules, run quick ephemeral bash-based smoke tests before handoff.
- Pattern: `python - <<'PY' ... PY` using isolated temp roots under `/tmp` (for example, `/tmp/workflow-run-check`).
- For runtime-dependent smoke tests, call `set_bootstrap_roots(data_root, system_root)` before importing modules that read settings/runtime paths.
- Favor targeted failure probes that assert exact error text/pointers (for example, bad directive value, missing step name).

## Common Mistakes
- Relying on free-form model output instead of deterministic artifacts.
- Adding noisy events instead of decision-boundary events.
- Treating smoke tests as a substitute for scenario coverage.
- Running `validation/run_validation.py` directly instead of requesting maintainer results.

## Phase Exit
Move to [Refactor and Hardening](refactor-and-hardening.md) once behavior is correct and covered.
