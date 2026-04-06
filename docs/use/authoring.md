# Workflow Authoring Contract

This document describes the current workflow authoring contract in AssistantMD.
Use it together with the inspectable authoring contract exposed by the authoring API.

## Overview

AssistantMD workflows live as markdown files under `AssistantMD/Workflows/`.
The current Python-based workflow path uses a constrained Python sandbox inside one fenced code block.

This is not full CPython. Prefer normal Python orchestration where it works, but assume that some standard-library and OS-backed runtime behavior may still be unavailable inside the sandbox.

The current built-in workflow capabilities are:

- `retrieve(...)` to read scoped external inputs into the workflow
- `generate(...)` to perform one explicit model call
- `output(...)` to write selected results out
- `call_tool(...)` to invoke one declared host tool explicitly

Capability results are returned as Python objects with attribute access, for example:

```python
source = await retrieve(type="file", ref="notes/today.md")
note_content = source.items[0].content

draft = await generate(
    prompt=f"Summarize this note:\n\n{note_content}",
    instructions="Be concise.",
)

await output(type="file", ref="reports/daily.md", data=draft.output)
```

A host-provided `date` object is also available for workflow-oriented date tokens such as:

- `date.today()`
- `date.tomorrow()`
- `date.yesterday()`
- `date.this_week()`
- `date.last_week()`
- `date.next_week()`
- `date.this_month()`
- `date.last_month()`
- `date.day_name()`
- `date.month_name()`

Each date method also supports an optional format string such as `date.today("YYYYMMDD")`.

## File Format

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

- `workflow_engine: monty` selects the constrained-Python workflow engine.
- `schedule:` is optional. Omit it for manual-only workflows.
- Supported schedule forms are:
  - `schedule: "cron: 0 9 * * *"` for recurring runs
  - `schedule: "once: 2026-01-15 14:30"` for one-time runs
- `enabled: true` or `enabled: false` controls whether scheduled runs are active.
- `description:` is optional but useful for workflow discovery.
- Top-level `authoring.*` properties are the canonical capability manifest shape for workflow files in Obsidian. File reads, file writes, and tool calls are fail-closed unless the relevant scope is declared there.

Example capability manifest:

```yaml
authoring.capabilities: [retrieve, generate, output, call_tool]
authoring.read_paths: [Tasks/**/*.md, Inbox/*.md]
authoring.write_paths: [Tasks/weekly/*.md, Reports/*.md]
authoring.tools: [file_ops_safe, internal_api]
```

After the frontmatter, the file must contain exactly one executable fenced Python block:

````markdown
```python
...
```
````

The executable workflow code belongs inside that block. Do not split execution across multiple Python blocks.

## Rules

- Use one markdown artifact with frontmatter and one fenced `python` block.
- Prefer explicit orchestration in Python over hidden framework behavior.
- Use built-in capabilities such as `retrieve(...)`, `generate(...)`, and `output(...)` for host boundary crossings.
- Treat frontmatter as a real security boundary, not documentation.
- `retrieve(type="file", ...)` is denied unless `authoring.read_paths` explicitly allows the target ref.
- `output(type="file", ...)` is denied unless `authoring.write_paths` explicitly allows the target ref.
- `call_tool(...)` is denied unless `authoring.tools` explicitly allowlists the tool name.
- Treat `type`, `ref`, and `options` as the stable contract shape for resource-oriented capabilities.
- Build prompts explicitly in Python so retrieved content can be placed exactly where it belongs.
- Prefer attribute access on returned objects, for example `source.items[0].content` and `draft.output`.
- Use the host-provided `date` object for workflow date tokens such as `date.today()` and `date.today("YYYYMMDD")`.
- Do not assume unrestricted imports, full stdlib support, or direct OS access inside the sandbox.
- Inspect the authoring contract before guessing capability arguments or return shapes.
- Use compile-only workflow testing before execution when validating a new or changed workflow.

Example:

```python
source = await retrieve(type="file", ref="notes/*.md", options={"limit": 3})

draft = await generate(
    prompt=(
        "Write a short summary of these notes.\n\n"
        + "\n\n".join(item.content for item in source.items)
    ),
    instructions="Be concise and factual.",
    model="gpt-mini",
)

await output(
    type="file",
    ref=f"reports/summary-{date.today()}.md",
    data=draft.output,
    options={"mode": "replace"},
)
```
