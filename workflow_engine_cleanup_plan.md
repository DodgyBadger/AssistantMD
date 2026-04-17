# Workflow Engine Cleanup Plan

## Goal

Remove `workflow_engine` from active code paths so `run_type` is the only discriminator for authored automation files under `AssistantMD/Authoring/`.

## Scope

- workflow loader validation
- workflow summary/API metadata
- scheduler and validation log payloads
- compile-only authoring helper behavior

## Implementation

1. Replace loader-side `workflow_engine` validation with `run_type` validation.
2. Require `run_type: workflow` for scheduler-managed workflow loading.
3. Replace `WorkflowDefinition.workflow_name` metadata with `run_type`.
4. Stop exposing `workflow_engine` in API summaries; expose `run_type` instead.
5. Replace validation log payload keys that still emit `engine`.
6. Remove remaining active-code references to `workflow_engine` in `core/authoring/service.py`.

## Validation

1. Compile touched Python modules.
2. Check diffs for formatting errors.
3. Verify no active-code `workflow_engine` references remain in `core/` and `api/`.
