# `workflow_run`

## Purpose

List authored automations in the current vault and run, start, inspect, cancel, enable, or disable them.

## When To Use

- you need to discover workflows in the current vault
- you want to run an authored automation manually and wait for the result
- you want to start a long-running workflow and check or cancel it later
- you want to enable or disable a workflow

## Operation Policy

Use `run` by default. It is synchronous: the call waits for the workflow to finish and returns the final result. This is the right choice for normal workflows that are expected to complete quickly.

Use `start` only for workflows that may take a long time or when the user explicitly wants the workflow to continue in the background. `start` returns immediately with a `task_id`; it does not mean the workflow has finished.

After `start`, use `status` with the returned `task_id` before reporting completion or using the workflow result. Use `cancel` with the same `task_id` if the user asks to stop the background workflow.

## Arguments

- `operation`: one of `list`, `run`, `start`, `status`, `cancel`, `enable_workflow`, `disable_workflow`
- `workflow_name`: workflow name relative to `AssistantMD/Authoring`
- `step_name`: optional step for `run` or `start`
- `task_id`: execution task id returned by `start`, required for `status` and `cancel`

## Examples

```python
workflow_run(operation="list")
```

```python
workflow_run(operation="run", workflow_name="weekly-planner")
```

```python
started = workflow_run(operation="start", workflow_name="nightly-memory-extraction")
```

```python
workflow_run(operation="status", task_id="task-id-from-start")
```

```python
workflow_run(operation="cancel", task_id="task-id-from-start")
```

## Output Shape

Returns plain text results for discovery, execution, or lifecycle operations.

## Notes

- the current vault is inferred from chat or workflow context
- use names relative to `AssistantMD/Authoring`
- `run` dispatches by `run_type`
- `run_type: workflow` executes the workflow path
- `run_type: context` performs a dry-run execution and reports assembled-context details
- `run` is synchronous and should be the default operation for ordinary workflow runs
- `start` is only for `run_type: workflow`; use `run` to dry-run context templates
- `start` is asynchronous and returns immediately with a `task_id`; use `status` before claiming the workflow is complete
- `cancel` requests cancellation for a workflow task in the current vault; mutated files are rolled back by the shared task lifecycle
- lifecycle operations only apply to `run_type: workflow`
