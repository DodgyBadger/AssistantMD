# Python Workflow Authoring

This document describes how to author `python_steps` workflows in AssistantMD.
Use it together with the inspectable SDK surface exposed by the authoring API.

## Overview

`python_steps` is a markdown-native workflow format. The workflow file is still a markdown note stored under `AssistantMD/Workflows/`, but the executable workflow body is written as a constrained Python SDK inside one fenced code block.

The Python block is not arbitrary Python. It supports a small declarative surface centered on `File`, `Var`, `Step`, and `Workflow`.

## File Format

Workflow files live under `AssistantMD/Workflows/` inside a vault.

Every `python_steps` workflow must include YAML frontmatter at the top of the file:

```yaml
---
workflow_engine: python_steps
enabled: false
description: Optional description
---
```

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
- Avoid helper functions, imports, loops, and arbitrary control flow. The supported surface is declarative.
