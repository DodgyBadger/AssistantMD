# Execution Task Coordinator Implementation Plan

## Purpose

Turn the execution task coordinator sketch into an implementation path grounded in the current codebase.

This plan leaves `EXECUTION_TASK_COORDINATOR_PLAN.md` as the concept sketch and defines the phased code work needed for:

- issue #32: workflow governor
- issue #33: cancellable chat responses
- issue #34: async `workflow_run` contract

The host-level noun is **execution task**. Use `run` only when referring to existing Pydantic AI agent runs or existing public names such as `workflow_run`.

## Current Code Shape

Runtime bootstrap is centralized in:

- `core/runtime/bootstrap.py`
- `core/runtime/context.py`
- `main.py`

`bootstrap_runtime()` creates the workflow loader, ingestion service, APScheduler instance, and `RuntimeContext`, registers it globally, synchronizes workflow jobs, schedules ingestion, and resumes the scheduler. `RuntimeContext.shutdown()` currently stops the scheduler and clears the global runtime context.

Workflow execution currently has three separate entry paths:

- scheduler jobs call `WorkflowDefinition.workflow_function`, which is currently `core.authoring.engine.run_workflow`
- `POST /api/workflows/execute` calls `api.services.execute_workflow_manually`
- `workflow_run(operation="run")` calls `WorkflowRun._execute_workflow`

All three eventually execute `core.authoring.service.run_authoring_template(...)`, but they duplicate loading, timing, result formatting, and error handling. Scheduler job functions must remain module-level and picklable because APScheduler uses a persistent SQLAlchemy job store.

Chat execution currently has two direct paths in `core/chat/executor.py`:

- non-streaming calls `prepared.agent.run(...)`, then persists `result.new_messages()`
- streaming iterates `prepared.agent.run_stream_events(...)`, emits SSE chunks, then persists `final_result.new_messages()`

Both paths have broad failure handling. Cancellation needs explicit handling before generic exception handling so cancelled work gets a deterministic terminal state and does not persist partial assistant messages.

API response models live in `api/models.py`, endpoints in `api/endpoints.py`, and most endpoint business logic in `api/services.py`. Existing validation scenarios already cover workflow lifecycle operations, API endpoints, chat persistence, and streaming failure logging under `validation/scenarios/integration/core/`.

## Target Architecture

Add one in-process execution task layer under `RuntimeContext`.

Proposed modules:

- `core/runtime/execution_tasks.py`: task records, snapshots, status transitions, cancellation
- `core/runtime/workflow_governor.py`: workflow-specific lane, overlap, timeout, and formatting policy
- `core/authoring/workflow_execution.py`: shared lower-level workflow execution helper that runs an already-resolved workflow without calling back through the governor

`RuntimeContext` should gain:

- `task_coordinator: TaskCoordinator`
- `workflow_governor: WorkflowGovernor`

The coordinator is not durable. It tracks active and recently terminal execution tasks in memory, logs lifecycle events, and marks in-flight tasks as interrupted/cancelled during shutdown.

## Phase 0: Workflow Execution Cleanup

Before introducing the coordinator, collapse the duplicated workflow execution plumbing into one shared internal helper.

Current duplication:

- `api.services.execute_workflow_manually(...)` loads the workflow, ensures directories, creates job args, measures elapsed time, catches errors, and formats response data.
- `WorkflowRun._execute_workflow(...)` repeats the same loading, directory setup, job args, timing, terminal status, and response formatting with slightly better loader-error details.
- scheduler execution is already thinner, but it calls the same `WorkflowDefinition.workflow_function` that the future governor must wrap carefully.

Cleanup target:

- add `core/authoring/workflow_execution.py`
- move shared workflow resolution and execution into that module
- keep API and tool-specific presentation formatting at the edges
- preserve existing blocking behavior and response fields
- preserve useful `workflow_run` configuration-error reporting
- do not introduce task ids, overlap policy, async start/status, or cancellation in this phase

This is not just cosmetic. It reduces the number of behavior surfaces that the governor has to intercept and makes Phase 3 mostly a policy wrapper around one execution path instead of a simultaneous refactor and behavior change.

Validation target:

- `POST /api/workflows/execute` still returns the current `ExecuteWorkflowResponse` shape
- `workflow_run(operation="run")` still returns the current text shape
- loader/configuration errors remain actionable from the tool path
- existing workflow lifecycle validation still passes

## Phase 1: Coordinator Foundation

Add `TaskCoordinator` with a small, explicit contract:

- create task ids
- register active coroutine work with kind, scope, source, label, and metadata
- expose immutable task snapshots
- cancel by task id
- cancel by scope
- mark terminal states: `completed`, `failed`, `cancelled`, `timed_out`, `skipped`
- retain a bounded in-memory terminal history

Suggested statuses:

- `queued`
- `running`
- `completed`
- `failed`
- `cancelled`
- `timed_out`
- `skipped`

Suggested scopes:

- `chat_session:<session_id>`
- `workflow_vault:<vault_name>`
- `workflow:<global_id>`
- `system`

Implementation notes:

- Use `asyncio.Task` internally for active cancellable work.
- Store public snapshots separately from private task handles.
- Guard coordinator state with an `asyncio.Lock`.
- Emit validation-friendly lifecycle log events such as `execution_task_created`, `execution_task_started`, `execution_task_completed`, `execution_task_failed`, `execution_task_cancel_requested`, and `execution_task_cancelled`.
- Treat `asyncio.CancelledError` as cancellation, not as a generic failure.

Bootstrap changes:

- instantiate `TaskCoordinator` before creating `RuntimeContext`
- attach it to `RuntimeContext`
- update `RuntimeContext.shutdown()` to request/cancel active tasks before scheduler shutdown

Validation target:

- unit-level or integration helper coverage for task status transitions, cancellation, bounded terminal history, and shutdown cleanup

## Phase 2: Workflow Execution Unification

Create a shared lower-level workflow executor that does the work currently duplicated by `api.services.execute_workflow_manually` and `WorkflowRun._execute_workflow`.

The helper should:

- validate `global_id`
- load the target workflow through `RuntimeContext.workflow_loader`
- surface loader configuration errors in the same useful style `workflow_run` has today
- ensure workflow directories
- create job args with `core.scheduling.jobs.create_job_args`
- call the underlying authoring template execution path
- return one structured result object/dict with status, reason, elapsed time, output files placeholder, and message

Important scheduler constraint:

- keep `core.authoring.engine.run_workflow` as the module-level picklable scheduler function
- change its body to resolve `get_runtime_context().workflow_governor.execute_workflow(...)`
- ensure the governor does not call `target.workflow_function(...)`, or it will recurse
- the governor should call the new lower-level helper or `run_authoring_template(...)` directly

Step-name note:

- `ExecuteWorkflowRequest.step_name` and `workflow_run(..., step_name=...)` exist today, but `core.authoring.engine.run_workflow` currently discards kwargs and Monty template execution does not appear to implement step selection.
- Preserve the accepted input for compatibility.
- In the first implementation slice, either pass it through as metadata only or return a clear unsupported response if callers depend on single-step execution. Do not silently claim selective execution unless the authoring runtime actually supports it.

Affected files:

- `core/authoring/engine.py`
- `core/authoring/service.py` or new `core/authoring/workflow_execution.py`
- `api/services.py`
- `core/tools/workflow_run.py`

Validation target:

- extend `validation/scenarios/integration/core/api_endpoints.py` to assert manual workflow execution still succeeds
- extend or add a workflow execution scenario that exercises API and tool execution through the same result contract

## Phase 3: Workflow Governor

Add `WorkflowGovernor` as the policy layer above shared workflow execution.

Initial policy:

- one active workflow execution task per vault
- overlap policy defaults to `skip`
- scheduled, manual API, and tool-triggered workflow execution all use the same governor path
- workflow timeout applies consistently across all three entry points

Suggested public method:

```python
await runtime.workflow_governor.execute_workflow(
    global_id=global_id,
    source="scheduler" | "api" | "tool",
    file_path=file_path,
    step_name=step_name,
    expect_failure=expect_failure,
)
```

Return shape should stay compatible with `ExecuteWorkflowResponse` and `workflow_run` formatting:

- `success`
- `global_id`
- `status`
- `execution_time_seconds`
- `output_files`
- `reason`
- `message`
- `task_id`

Settings:

- add `workflow_task_timeout_seconds` to `core/settings/settings.template.yaml`
- add a settings accessor in `core/settings/__init__.py`
- use `0` as disabled if that matches existing settings style
- consider `workflow_overlap_policy` later; keep `skip` hardcoded for the first slice unless a UI-configurable policy is required immediately

Logging events:

- `workflow_task_started`
- `workflow_task_completed`
- `workflow_task_failed`
- `workflow_task_cancelled`
- `workflow_task_timed_out`
- `workflow_task_overlap_skipped`

Affected files:

- `core/runtime/bootstrap.py`
- `core/runtime/context.py`
- `core/runtime/workflow_governor.py`
- `core/settings/settings.template.yaml`
- `core/settings/__init__.py`
- `core/scheduling/jobs.py`
- `core/authoring/engine.py`
- `api/services.py`
- `core/tools/workflow_run.py`

Validation target:

- add `validation/scenarios/integration/core/workflow_governor.py`
- use a controllable long-running workflow to trigger an overlapping manual/tool execution
- assert only one active workflow task exists for the vault
- assert skipped overlap returns `status="skipped"` with a structured reason
- assert validation log includes `workflow_task_overlap_skipped`

## Phase 4: Task Status And Cancellation API

Add API models in `api/models.py`:

- `ExecutionTaskInfo`
- `ExecutionTaskListResponse`
- `ExecutionTaskCancelResponse`

Add endpoint/service methods:

- `GET /api/tasks`
- `GET /api/tasks/{task_id}`
- `POST /api/tasks/{task_id}/cancel`
- `GET /api/chat/sessions/{session_id}/active-task`
- `POST /api/chat/sessions/{session_id}/cancel`
- optionally `GET /api/workflows/tasks?vault_name=...`

Contract:

- task snapshots are process-local
- unknown task id returns a structured 404
- cancelling an already terminal task is idempotent and returns its current terminal status
- cancellation request sets `cancel_requested=True` immediately even if cooperative cancellation takes time

Affected files:

- `api/models.py`
- `api/endpoints.py`
- `api/services.py`

Validation target:

- extend `validation/scenarios/integration/core/api_endpoints.py` for task list/detail/cancel shape
- add a focused scenario for idempotent cancel of terminal and unknown tasks

## Phase 5: Chat Cancellation

Wrap chat execution with task registration scoped to `chat_session:<session_id>`.

Non-streaming path:

- prepare chat as today
- execute `prepared.agent.run(...)` inside a coordinator-managed task
- cancel by task id or session id
- on cancellation, do not persist `result.new_messages()`
- return a deterministic cancellation API error/response shape

Streaming path:

- task lifetime should span the async generator, not only preflight
- cancellation should stop `prepared.agent.run_stream_events(...)`
- when possible, emit a terminal SSE cancellation event before the generator exits
- do not persist partial assistant messages after cancellation
- preserve existing streaming failure behavior validated by `chat_stream_failure_logging.py`

Implementation caution:

- Broad `except Exception` blocks in `api/endpoints.py` and `core/chat/executor.py` should not convert cancellation into generic unexpected errors.
- Handle cancellation before generic error paths.
- Keep `ChatContextTemplateError` and capability mismatch behavior unchanged.

Affected files:

- `core/chat/executor.py`
- `api/endpoints.py`
- `api/services.py`
- `api/models.py`

Validation target:

- add `validation/scenarios/integration/core/chat_cancellation.py`
- use a fake or controllable long-running agent/tool path
- start chat, cancel by session, assert active task becomes `cancelled`
- assert no partial transcript is persisted for cancelled streaming chat
- assert existing `chat_session_persistence_contract.py` and `chat_stream_failure_logging.py` behavior remains intact

## Phase 6: Async `workflow_run` Contract

After the governor and task API exist, add async operations to the tool without breaking `operation="run"`.

Suggested operations:

- `start`: create workflow execution task and return `task_id`
- `status`: return current or terminal snapshot by `task_id`
- `cancel`: request cancellation by `task_id`
- `run`: keep blocking behavior, now implemented through the governor

Do not expose governor internals through the tool. The tool should format task snapshots in a compact, stable text contract suitable for agents.

Affected files:

- `core/tools/workflow_run.py`
- `docs/tools/workflow_run.md`
- `validation/scenarios/integration/core/workflow_lifecycle_ops.py` or a new async workflow tool scenario

Validation target:

- start an async workflow task from `workflow_run`
- poll status until terminal
- cancel a long-running task
- assert `operation="run"` remains backward compatible

## Phase 7: UI Integration

Once backend cancellation and task snapshots are stable:

- show active chat task state for the current session
- add a chat cancel control when a response is active
- show workflow task status where manual workflow execution is triggered
- avoid durable history UI until the backend intentionally persists task history

Likely files:

- API client code under `static/` or frontend scripts
- templates served by the FastAPI UI
- CSS only if required; remember `npm run build:css` compiles `static/input.css` to `static/output.css`

Validation target:

- targeted browser or API smoke check for cancel control state
- do not run full validation locally; maintainers own full validation

## Sequencing Recommendation

Implement in this order:

0. Preliminary workflow execution cleanup: remove duplicated loading/timing/result formatting across API and tool paths while preserving current behavior.
1. Coordinator foundation and runtime bootstrap integration.
2. Shared workflow executor without changing external behavior.
3. Workflow governor for scheduled/API/tool workflow execution.
4. Task status/cancel API.
5. Chat cancellation.
6. Async `workflow_run` operations.
7. UI controls.

This gets the workflow governor foundation in place before chat cancellation and async tool contracts depend on it.

## Key Risks

- APScheduler job persistence can break if scheduled job functions stop being importable module-level callables.
- Governor recursion can happen if the governor calls `WorkflowDefinition.workflow_function` after `engine.run_workflow` delegates to the governor.
- Existing `step_name` parameters are accepted but not actually implemented by the current Monty execution path.
- Cancellation can be misclassified as generic failure if broad exception handlers catch it first.
- Streaming chat task lifetime is tied to async generator consumption, so task cleanup must happen in `finally` paths.
- In-memory task snapshots disappear on restart by design; API and docs should state process-local status only.

## Phase Exit Criteria

The planning phase is complete when this file is committed or otherwise preserved at the repo root.

Phase 0 has been implemented by extracting `core/authoring/workflow_execution.py` and routing the existing API and tool workflow execution paths through it.

Phase 1 has been implemented by adding `core/runtime/execution_tasks.py`, attaching `TaskCoordinator` to `RuntimeContext`, and cancelling active tracked tasks during runtime shutdown.

Phase 2/3 has been implemented by adding `core/runtime/workflow_governor.py`, using the shared workflow executor as the governor's lower-level execution path, routing scheduled/API/tool workflow execution through the governor, and adding the `workflow_task_timeout_seconds` setting.

Phase 4 has been implemented by adding task list/detail/cancel endpoints, workflow task listing, chat active-task/cancel endpoints, and validation coverage in `validation/scenarios/integration/core/api_endpoints.py`.

Phase 5 has been implemented by routing non-streaming and streaming chat execution through the coordinator, adding cancellation handling that avoids partial persistence, and adding `validation/scenarios/integration/core/chat_cancellation.py`.

The next phase should be feature development starting with Phase 6: add async `workflow_run` operations for start/status/cancel while preserving the existing blocking `run` operation.
