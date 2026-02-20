# Workflow Guide

A workflow is a markdown file stored under each vault's `AssistantMD/Workflows/` folder. Workflows can be organized in subfolders (one level deep). Subfolders beginning with an underscore are ignored.

## Structure
YAML frontmatter between `---` delimiters (required). These appear as properties if using Obsidian.
Sets the run schedule and the workflow engine to run. Currently there is only one workflow engine called step.

`## Instructions` section with a prompt that is included as a system instruction before every step prompt.

`## Step`: Any other `##` heading that does not include the word "instructions" is treated as a workflow step.
- Steps execute in the order they appear.
- Steps can be configured to generate information for later steps or write files to your vault.
- Context is not passed automatically between steps. Use `@output variable:foo` + `@input variable:foo` to pass context (or `file:name` if you want greater observability).

> See [reference](reference.md) for details on all the control primitives available for workflow templates.

Following is a complete, valid workflow template. Copy the text into `AssistantMD/Workflows/` inside any vault, change the model as needed, rescan your vaults and then run manually to test the results.

**NOTE**: Workflow files must include only the text below, not embedded inside a markdown code block. If you are pasting into a new note in Obsidian, use `ctrl-shift-v` (or right-click `Paste as plain text`) to avoid pasting the code block. The top section should immediately render as Obsidian Properties.

```
---
schedule: "cron: 0 9 * * *"
workflow_engine: step
enabled: false
description: Daily poet
---

## Instructions
You are a helpful assistant.

## Daily haiku
@output file: test/{today}
@header Weekly Haiku
@model gpt-mini

Write a haiku to go with the current season or nearest holiday.

## Haiku critic
@output file: test/{today}
@input file: test/{today}
@write_mode append
@header Haiku feedback
@model gpt-mini

Read the haiku above and provide your feedback.
- Does it meet the criteria of being appropriate to the current season or nearest holiday?
- Does it follow proper haiku structure?
- Is the imagery compelling?
- How could it be improved?
```


