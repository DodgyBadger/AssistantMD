# Live Suite Triage Plan

## Scope
- Reduce `validation/scenarios/integration/live` to the smallest set of live-only happy-path checks that still provide coverage not available in `integration/core`.
- Remove scenarios that still depend on the retired step-DSL under `AssistantMD/Workflows` and `workflow_engine: step`.
- Identify any live scenario intent worth preserving, but only after rewriting it to current Monty authoring or direct API flows.

## Current Assessment
- `validation/scenarios/integration/live/import_pipeline_live_url.py`
  - Keep for now.
  - It exercises `/api/import/url` against a real external fetch target and does not depend on the removed DSL.
- `validation/scenarios/integration/live/api_tools_live_smoke.py`
  - Delete in current form.
  - Uses `AssistantMD/Workflows/status_probe.md` with step-DSL syntax.
  - Intent may still matter later as a replacement Monty or direct chat-tool live smoke.
- `validation/scenarios/integration/live/browser_policy_live.py`
  - Delete in current form.
  - Entire scenario is step-DSL based.
  - Its behavioral intent is also a poor fit for live coverage because the inputs are deterministic and should be covered by cheaper core/integration scenarios.
- `validation/scenarios/integration/live/image_provider_smoke.py`
  - Delete in current form.
  - Uses step-DSL.
  - Live multimodal provider smoke may still be worth keeping later, but only as a rewritten Monty workflow or direct chat/API scenario.
- `validation/scenarios/integration/live/tool_output_routing.py`
  - Delete.
  - Uses step-DSL.
  - The feature itself is not a good live target because it should be deterministic and belong in core if still relevant.
- `validation/scenarios/integration/live/tool_suite_live.py`
  - Delete.
  - Uses step-DSL.
  - It is broad, expensive, and overlaps with cheaper deterministic coverage already present in `integration/core/authoring_contract.py`, `integration/core/code_execution_local.py`, and `integration/core/workflow_lifecycle_ops.py`.

## Overlap Notes
- `integration/core/api_endpoints.py` already covers:
  - chat endpoint health
  - metadata exposure for tools including `workflow_run`
  - basic chat execution and streaming
  - image capability mismatch path
- `integration/core/authoring_contract.py` already covers deterministic helper/tool-first authoring behavior including:
  - `file_ops_safe`
  - `file_ops_unsafe`
  - markdown parsing
  - pending files
  - `assemble_context(...)`
- `integration/core/workflow_lifecycle_ops.py` already covers `workflow_run` lifecycle behavior.
- `integration/core/import_pipeline_core.py` already covers import scan for local files.

## First-Pass Deletes
- `validation/scenarios/integration/live/api_tools_live_smoke.py`
- `validation/scenarios/integration/live/browser_policy_live.py`
- `validation/scenarios/integration/live/image_provider_smoke.py`
- `validation/scenarios/integration/live/tool_output_routing.py`
- `validation/scenarios/integration/live/tool_suite_live.py`

## Keep For Now
- `validation/scenarios/integration/live/import_pipeline_live_url.py`

## Candidate Replacements Later
- Add one minimal live multimodal happy-path scenario if we still need a real provider image-input smoke.
- Add one minimal live chat tool-invocation smoke only if `integration/core` proves insufficient for provider-side tool-call compatibility.
- Keep replacements narrow: one behavior per scenario, no suites-of-suites.

## Validation Target
- Short term: remove obsolete live scenarios and keep the live suite lean.
- Follow-up: run `python validation/run_validation.py run integration/live` and patch only current-contract scenarios that remain.

## Next Phase
- Move to Feature Development to delete the obsolete live scenarios and then reassess whether any replacement live smoke is needed.
