# Python Workflow Authoring

This document describes how to author `python_steps` workflows in AssistantMD.
Use it together with the inspectable SDK surface exposed by the authoring API.

## Overview

`python_steps` is a markdown-native workflow format. The workflow file is still a markdown note stored under `AssistantMD/Workflows/`, but the executable workflow body is written as a constrained Python SDK inside one fenced code block.

The Python block is not arbitrary Python. It supports a small declarative surface centered on `File`, `Var`, `Step`, and `Workflow`, plus SDK-owned helper namespaces such as `date` and `path`.

## File Format

Workflow files live under `AssistantMD/Workflows/` inside a vault.

Every `python_steps` workflow must include YAML frontmatter at the top of the file:

```yaml
---
workflow_engine: python_steps
schedule: "cron: 0 9 * * *"
enabled: false
description: Optional description
---
```

Frontmatter notes:
- `workflow_engine: python_steps` selects the Python workflow engine.
- `schedule:` is optional. Omit it for manual-only workflows.
- Supported schedule forms are:
  - `schedule: "cron: 0 9 * * *"` for recurring runs
  - `schedule: "once: 2026-01-15 14:30"` for one-time runs
- `enabled: true` or `enabled: false` controls whether scheduled runs are active.
- `description:` is optional but useful for workflow discovery.

After the frontmatter, the file must contain exactly one executable fenced Python block:

````markdown
```python
...
```
````

The executable workflow code belongs inside that block. Do not split execution across multiple Python blocks.

## Rules

- Use top-level assignments for reusable constants, `Step(...)` declarations, and the `Workflow(...)` declaration.
- Reusable constants may be plain literals or SDK-bound values such as `File(...)`, `Var(...)`, `File(...).replace()`, and `Var(...).append()`.
- `Step(...)` and `Workflow(...)` currently require keyword arguments, not positional arguments.
- Declare steps first, then reference those declared step variables inside `Workflow(steps=[...])`.
- End the Python block with `workflow.run()` to mark the execution entrypoint.
- Only one `Workflow(...)` declaration is allowed.
- Inputs must use `File(...)` or `Var(...)`.
- Outputs must use `File(...)`, `Var(...)`, or supported target methods such as `.replace()` and `.append()`.
- Use `path.join(...)` with `date.*()` helpers for dynamic SDK paths.
- Keep globs as plain strings, for example `File("notes/*")`.
- Do not use raw brace substitutions like `File("daily/{today}")` in the Python SDK. That syntax belongs to the string DSL.
- Avoid helper functions, imports, loops, and arbitrary control flow. The supported surface is declarative.

Examples:

```python
today_note = File(path.join("daily", date.today()))
weekly_note = File(path.join("weekly", date.this_week()))
short_month = File(path.join("plans", date.month_name(fmt="MMM")))
glob_input = File("notes/*")
```
