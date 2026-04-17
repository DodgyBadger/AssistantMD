# Workflow Authoring Guide

This document describes the workflow-specific file shape used when authoring constrained-Python workflows in AssistantMD.

For constrained runtime helper signatures and examples, read:

- `__virtual_docs__/tools/code_execution_local.md`

Use this guide for workflow-specific structure:

- markdown artifact location
- frontmatter fields
- compile-before-run workflow habits

## Workflow File Shape

Workflow files live under `AssistantMD/Authoring/` inside a vault.

Every constrained-Python workflow should include YAML frontmatter at the top of the file:

```yaml
---
run_type: workflow
schedule: "cron: 0 9 * * *"
enabled: false
description: Optional description
---
```

Frontmatter notes:

- `run_type: workflow` marks the file as a scheduler-managed workflow
- `schedule:` is optional; omit it for manual-only workflows
- `enabled: true` or `enabled: false` controls whether scheduled runs are active
- `description:` is optional but useful for workflow discovery

After the frontmatter, the file must contain exactly one executable fenced Python block:

````markdown
```python
...
```
````

The executable workflow code belongs inside that block. Do not split execution across multiple Python blocks.

## Workflow Authoring Rules

- Treat `AssistantMD/Authoring/` as the canonical home for workflow templates.
- Use the constrained runtime doc to inspect helper signatures before guessing arguments or return shapes.
- Use compile-only workflow testing before execution when validating a new or changed workflow.
- Keep workflow changes small, testable, and easy to review.
- Prefer explicit orchestration in Python over hidden framework behavior.
