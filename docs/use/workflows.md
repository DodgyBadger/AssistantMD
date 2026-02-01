# Workflow Guide

A workflow is a markdown file stored under each vault's `AssistantMD/Workflows/` folder. Workflows can be organized in subfolders (one level deep). Subfolders beginning with an underscore are ignored.

## Structure
- YAML frontmatter between `---` delimiters (required). These appear as properties if using Obsidian.
Sets the run schedule and the workflow engine to run. Currently there is only one workflow engine called step.
- Optional `## Instructions` section with a prompt that is included as a system instruction before every step prompt.
- One or more `## Headers` which define the steps to run. The header name can be anything - every `## Header` found after Instructions is interpretted as a step, running in the order they appear.

Following is a complete, valid workflow definition. Copy the text into `AssistantMD/Workflows/` inside any vault, change the model as needed, rescan your vaults, and then run it manually to see the results. Both operations are available on the Workflow tab of the web interface.

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
@write-mode append
@header Haiku feedback
@model gpt-mini

Read the haiku above and provide your feedback.
- Does it meet the criteria of being appropriate to the current season or nearest holiday?
- Does it follow proper haiku structure?
- Is the imagery compelling?
- How could it be improved?
```

---

Explore detailed documentation for each component:

- **[Reference](reference.md)** - Directives, frontmatter, patterns, buffers, and routing

Note: Workflows now support buffer variables (`variable:` targets) and routing (`output=...`, `write-mode=...`) so steps can redirect inputs and tool outputs without inline prompts. See Reference for syntax.
