# `workflow_run`

## Purpose

List authored automations in the current vault and run, enable, or disable them.

## When To Use

- you need to discover workflows in the current vault
- you want to run an authored automation manually
- you want to enable or disable a workflow

## Arguments

- `operation`: one of `list`, `run`, `enable_workflow`, `disable_workflow`
- `workflow_name`: workflow name relative to `AssistantMD/Authoring`
- `step_name`: optional step for `run`

## Examples

```python
workflow_run(operation="list")
```

```python
workflow_run(operation="run", workflow_name="weekly-planner")
```

## Output Shape

Returns plain text results for discovery, execution, or lifecycle operations.

## Notes

- the current vault is inferred from chat or workflow context
- use names relative to `AssistantMD/Authoring`
- `run` dispatches by `run_type`
- `run_type: workflow` executes the workflow path
- `run_type: context` performs a dry-run execution and reports assembled-context details
- lifecycle operations only apply to `run_type: workflow`
