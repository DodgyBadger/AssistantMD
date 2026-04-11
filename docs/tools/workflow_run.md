# `workflow_run`

## Purpose

List workflows in the current vault and run, test, enable, or disable them.

## When To Use

- you need to discover workflows in the current vault
- you want to test a workflow definition
- you want to run a workflow manually
- you want to enable or disable a workflow

## Arguments

- `operation`: one of `list`, `test`, `run`, `enable_workflow`, `disable_workflow`
- `workflow_name`: workflow name relative to `AssistantMD/Workflows`
- `step_name`: optional step for `run`

## Examples

```python
workflow_run(operation="list")
```

```python
workflow_run(operation="test", workflow_name="weekly-planner")
```

```python
workflow_run(operation="run", workflow_name="weekly-planner")
```

## Output Shape

Returns plain text results for discovery, validation, execution, or lifecycle operations.

## Notes

- the current vault is inferred from chat or workflow context
- use names relative to `AssistantMD/Workflows`
- `test` currently performs lightweight validation rather than full rollback-aware execution
