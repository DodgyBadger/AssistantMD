# Workflow Authoring Guide

This document describes the workflow-specific file shape used when authoring constrained-Python workflows in AssistantMD.

For constrained runtime helper signatures and examples, read:

- `__virtual_docs__/tools/code_execution_local.md`

Use this guide for workflow-specific structure:

- markdown artifact location
- frontmatter fields
- workflow capability manifest shape
- compile-before-run workflow habits

## Workflow File Shape

Workflow files live under `AssistantMD/Workflows/` inside a vault.

Every constrained-Python workflow should include YAML frontmatter at the top of the file:

```yaml
---
workflow_engine: monty
schedule: "cron: 0 9 * * *"
enabled: false
description: Optional description
---
```

Frontmatter notes:

- `workflow_engine: monty` selects the constrained-Python workflow path during transition
- `schedule:` is optional; omit it for manual-only workflows
- `enabled: true` or `enabled: false` controls whether scheduled runs are active
- `description:` is optional but useful for workflow discovery

Capability manifest notes:

- top-level `authoring.*` properties are the canonical scope shape for workflow files
- file reads, cache reads, file writes, cache writes, and tool calls are fail-closed unless the relevant scope is declared

Example capability manifest:

```yaml
authoring.capabilities: [retrieve, generate, output, call_tool]
authoring.retrieve.file: [Tasks/**/*.md, Inbox/*.md]
authoring.retrieve.cache: [research/*, scratch/*]
authoring.output.file: [Tasks/weekly/*.md, Reports/*.md]
authoring.output.cache: [research/*, scratch/*]
authoring.tools: [file_ops_safe]
```

After the frontmatter, the file must contain exactly one executable fenced Python block:

````markdown
```python
...
```
````

The executable workflow code belongs inside that block. Do not split execution across multiple Python blocks.

## Workflow Authoring Rules

- Treat `AssistantMD/Workflows/` as the canonical home for workflow templates.
- Use the constrained runtime doc to inspect helper signatures before guessing arguments or return shapes.
- Use compile-only workflow testing before execution when validating a new or changed workflow.
- Keep workflow changes small, testable, and easy to review.
- Prefer explicit orchestration in Python over hidden framework behavior.
