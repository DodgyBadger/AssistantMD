# Integration Validation Suite Refactor Plan

Purpose: simplify overlap, strengthen behavioral contracts, and reduce live LLM/tool/network dependence in default integration runs.

Cross-reference architecture coverage target: [docs/architecture/README.md](/app/docs/architecture/README.md).

## Branch Priority: Image Integration PR Readiness

This branch is image-focused and not yet merged. Refactor priority should explicitly bias toward multimodal confidence before broader suite cleanup.

PR readiness for this branch requires:
1. Strong deterministic contract coverage of image prompt assembly and image-related directives.
2. At least one minimal live multimodal smoke scenario proving real provider compatibility with image payloads.
3. Clear separation between image-internal behavior checks (core) and provider smoke checks (live).

## Current Issues

1. Live `gpt-mini` calls are used in multiple scenarios where assertions are event/artifact based, so the LLM call is not the behavior under test.
2. Primitive coverage is now fragmented across several deterministic scenarios, increasing maintenance and drift risk.
3. Tool tests mix directive/routing contract checks with external/live tool smoke checks.
4. Ingestion coverage relies mostly on output heuristics and live URL fetch, with weak event contracts.

## Coverage Goals

1. Strong subsystem and user-journey coverage for:
- Runtime, Scheduler, Workflow Loader
- Engines + Directives
- LLM + Tools
- Context Manager
- API + settings/secrets flows
- Ingestion pipeline
- Multimodal prompt assembly behavior

2. Default integration suite should be deterministic and event-driven.
3. Live model/network/tool checks should be isolated to explicit smoke scenarios.

## Proposed Suite Structure

## `validation/scenarios/integration/core/`
- Deterministic (`@model test` / `@model none`) and validation-event heavy.
- Safe for regular/local default runs.

## `validation/scenarios/integration/live/`
- Real model/provider/network smoke coverage only.
- Small and intentionally expensive/flaky by nature.

## Image-Coverage Target State

## Core image contract scenario (deterministic)

Create or evolve `image_input_policy.py` into `image_contract.py` under `integration/core/` with `@model test`.

Coverage requirements:
1. Direct image `@input` attachment behavior:
- attached image count
- image reference material included in prompt artifacts

2. Embedded markdown image resolution:
- resolvable embedded image is attached
- unresolved embedded image yields warning + explicit placeholder

3. Image policy directives:
- `images=ignore` excludes attachment while preserving textual reference behavior
- mixed text + image inputs preserve stable assembly ordering in prompt artifacts

4. Regression hooks:
- assert against `workflow_step_prompt` event payload (`prompt`, `attached_image_count`, `prompt_warnings`)
- avoid relying on free-form model response text

## Live image smoke scenario (minimal)

Add `integration/live/image_provider_smoke.py`:
1. Single-step workflow with one direct image input.
2. Real model/provider call (one call only).
3. Assertions:
- request succeeds (HTTP/workflow success)
- non-empty output artifact exists
- `workflow_step_prompt` shows at least one attached image

This gives end-to-end provider confidence without making core runs expensive.

## Scenario-by-Scenario Recommendations

## Keep (Core)

1. `system_startup.py`
- Keep as primary Runtime/Scheduler/Loader resilience contract.
- Already strong on `workflow_loaded`, `job_synced`, `workflow_load_failed`, restart persistence.

2. `primitives_contract.py`
- Keep as central directives/patterns contract scenario.
- Continue expanding here instead of adding narrow primitive scenarios elsewhere.

3. `pending_hybrid.py`
- Keep as focused `{pending}` hybrid behavior contract.
- Minimal overlap with other scenarios.

4. `image_input_policy.py` -> `integration/core/image_contract.py`
- Keep as the canonical multimodal prompt-assembly contract.
- Switch `@model gpt-mini` to `@model test` because assertions are event/prompt based.
- Expand to cover direct image, embedded image, missing image, and `images=ignore` directive behavior in one contract scenario.

5. `api_endpoints.py` (split; core portion stays)
- Keep endpoint lifecycle assertions in core.
- Convert chat path to deterministic model where possible.

## Keep but Refactor

1. `context_manager_cache_modes.py`
- Keep for cache semantics and invalidation coverage.
- Switch template sections from `@model gpt-mini` to `@model test`.
- Assertions already rely on `context_cache_hit/miss`, `reason`, and `output_hash`.

2. `tool_output_routing.py`
- Keep for routing contracts.
- Minimize live dependence by preferring deterministic routing checks and validation events.

3. `import_pipeline.py`
- Split into:
  - `import_pipeline_core.py` (local PDF/import scan path, deterministic)
  - `import_pipeline_live_url.py` (URL ingest smoke only)
- Add ingestion validation events and assert against them where possible.

## Merge Into `primitives_contract.py`, Then Retire

1. `input_params.py`
- Merge unique coverage:
  - virtual docs resolution case (`__virtual_docs__/...`)
  - parentheses path handling
- Retire standalone scenario after merge. (done)

2. `buffer_variables.py`
- Merge buffer append/replace/refs_only/required variable checks.
- Retire standalone scenario after merge. (done)

3. `pattern_substitution.py` (partial merge)
- Merge any missing tokens not already in primitives:
  - `yesterday`, `tomorrow`, `last-week`, `next-week`, `last-month`
  - format variants (`YYYYMMDD`, `ddd`, `MMM`)
- Retire standalone scenario if full token coverage exists in primitives.

4. `context_manager.py` -> `basic_haiku_context_template.py`
- Refactor into a live-model happy-path scenario (kept in `integration/` root).
- Keep broad permutation/contract checks in core scenarios (`primitives_contract.py`, `context_manager_cache_modes.py`).

## Move to Live Smoke Suite

1. `tool_suite.py` -> `integration/live/tool_suite_live.py`
- Purpose: verify real tool/provider paths work with real model/provider wiring.
- Keep minimal steps; avoid broad “all tools” coverage in default core runs.

2. Add `integration/live/image_provider_smoke.py`
- Purpose: verify real multimodal model/provider path for image payloads.
- Keep to one call and one assertion chain.

3. API chat tool smoke slice from `api_endpoints.py`
- Optional extraction to `integration/live/api_tools_live_smoke.py`:
  - workflow_run through chat with real model/provider.

## Potential Retirement

1. `basic_haiku.py`
- Intentionally kept as the canonical quick happy-path smoke test.

## Implementation Phases

## Phase 0: Image Branch PR Gate (Do First)
1. Refactor `image_input_policy.py` into deterministic `integration/core/image_contract.py`.
2. Add `integration/live/image_provider_smoke.py` (single-call multimodal smoke).
3. Define PR gate:
- core image contract passes
- live image smoke passes
- no increase in default core live-model call count

## Phase 1: Cost/Flake Reduction (No Behavior Loss)
1. Switch deterministic-eligible scenarios from `gpt-mini` to `test`:
- `context_manager.py`
- `context_manager_cache_modes.py`
- chat sections of `api_endpoints.py`
2. Keep assertions unchanged; verify pass/fail signal quality.

## Phase 2: Primitive Consolidation
1. Expand `primitives_contract.py` with unique cases from:
- `input_params.py`
- `buffer_variables.py`
- missing token coverage from `pattern_substitution.py`
2. Retire redundant standalone files after parity is confirmed.

## Phase 3: Context Consolidation
1. Merge `context_manager.py` unique checks into deterministic contract coverage.
2. Keep `context_manager_cache_modes.py` as dedicated cache-invalidations contract.

## Phase 4: Live Suite Isolation
1. Move `tool_suite.py` to `integration/live`.
2. Extract optional live API chat-tool smoke from `api_endpoints.py`.
3. Split ingestion URL live check from core ingestion test.

## Recommended Guardrails

1. For each merged/retired scenario, maintain a “coverage checklist” in PR notes:
- event names asserted before vs after
- artifact assertions before vs after
- any removed assertions and rationale

2. Prefer event-contract assertions at decision boundaries over free-form response checks.
3. Keep live tests intentionally few and explicitly labeled as smoke.

## Quick Win Backlog (Ordered)

1. [x] Refactor `image_input_policy.py` to deterministic `integration/core/image_contract.py`.
2. [x] Add `integration/live/image_provider_smoke.py` with one real multimodal call.
3. [x] Convert `context_manager_cache_modes.py` templates to `@model test`.
4. [x] Convert chat model usage in `api_endpoints.py` and helper workflow to deterministic model where possible.
5. [x] Merge `input_params.py` unique cases into `primitives_contract.py`.
6. [x] Merge `buffer_variables.py` into `primitives_contract.py`.
7. [x] Decide whether to fully merge/retire `pattern_substitution.py`. (decision: fully merge into `primitives_contract.py`; standalone scenario retired)
8. [x] Move `tool_suite.py` into `integration/live/`.
9. [x] Split `import_pipeline.py` core vs live URL.
