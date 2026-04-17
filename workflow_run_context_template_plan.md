# Workflow Run Context Template Plan

## Scope

Investigate how `workflow_run` should operate now that workflows and context templates share the unified `AssistantMD/Authoring/` surface, and identify the smallest useful expansion that helps an LLM self-test authored automations.

## Current State

1. `workflow_run(operation="test")` already uses `compile_candidate_workflow(...)`, and that compile-only path accepts both `run_type: workflow` and `run_type: context`.
2. `workflow_run(operation="run")` still routes through the scheduler/workflow loader path, and the loader explicitly skips `run_type: context` files.
3. Context-template runtime execution today is chat-session-centric:
   - it uses the context manager history processor
   - it can depend on `message_history`, `chat_session_id`, and `memory_ops`
   - successful execution may only produce assembled context rather than vault files

## Affected Areas

- `core/tools/workflow_run.py`
- `core/authoring/service.py`
- `core/authoring/runtime/host.py`
- `core/authoring/context_manager.py`
- `docs/tools/workflow_run.md`
- validation scenarios around `workflow_run`

## User-Facing Goal

Let the chat agent use one tool surface to validate authored automations under `AssistantMD/Authoring/`, while preserving a clear distinction between:

- compile-only structural validation
- executable workflow runs that can produce inspectable side effects
- context-template dry runs that can confirm runtime correctness even when no files are produced

## Recommended Direction

1. Remove `workflow_run(test)` because it only provides superficial compile-time checks.
2. Add explicit `run_type` reporting to `workflow_run(list)` results so the model can reason about what kind of artifact it is invoking.
3. Keep `workflow_run(run)` as the single execution entry point, but dispatch by `run_type`.
4. For context execution support, use a dry-run contract:
   - execute the Monty block with a synthetic host/session
   - return terminal status, reason, print count, and assembled-context summary
   - include counts such as message count and instruction count when `assemble_context(...)` is returned
   - note whether file-writing tools were invoked so the agent knows whether vault artifacts may exist to inspect

## Validation Target

- Extend `validation/scenarios/integration/core/workflow_lifecycle_ops.py` or add a sibling scenario for `workflow_run` authoring test coverage.
- Add one `run_type: workflow` file and one `run_type: context` file under `AssistantMD/Authoring/`.
- Assert:
  - list output includes both artifact type and name
  - workflow run succeeds for `run_type: workflow`
  - context dry-run returns structured execution metadata
  - lifecycle operations reject `run_type: context`

## Next Phase

Move to Feature Development to implement the smallest useful slice:

1. enrich `list` output with `run_type`
2. add explicit context-aware execution behavior to `workflow_run`
3. document the resulting contract
