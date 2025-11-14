# Assistant Setup Guide

An assistant is a markdown file in a vault's `assistants/` folder that defines a scheduled AI workflow. Assistants can be in subfolders (one level deep) for better organization. Folders prefixed with underscore (e.g., `_chat-sessions`) are ignored.

**Basic Structure**  
- YAML frontmatter between `---` delimiters (required). These appear as properties if using Obsidian.
Sets the run schedule and the workflow engine to run. Currently there is only one workflow engine called step.
- Optional `## Instructions` section with a prompt that is included as a system instruction before every step prompt.
- One or more `## Headers` which define the steps to run. The header name can be anything - every `## Header` found after Instructions is interpretted as a step, running in the order they appear.

Following is a complete and valid assistant file example. Copy and paste the text into a markdown file in your assistants folder, change the model as needed, rescan your vaults and then run it manually to see the results. Both operations are found on the Dashboard tab of the web interface.

**NOTE**: Assistant files must include only the text below, not embedded inside a markdown code block. If you are pasting into a new note in Obsidian, use `ctrl-shift-v` (or right-click `Paste as plain text`) to make sure it doesn't include the code block. You should see the top section immediately turn into Obsidian Properties.

```
---
schedule: "cron: 0 9 * * *"
workflow: step
enabled: false
description: Daily poet
---

## Instructions
You are a helpful assistant.

## Daily haiku
@output-file test/{today}
@header Weekly Haiku
@model gpt-5-mini

Write a haiku to go with the current season or nearest holiday.

## Haiku critic
@output-file test/{today}
@input-file test/{today}
@write-mode append
@header Haiku feedback
@model gpt-5-mini

Read the haiku above and provide your feedback.
- Does it meet the criteria of being appropriate to the current season or nearest holiday?
- Does it follow proper haiku structure?
- Is the imagery compelling?
- How could it be improved?
```

---

Explore detailed documentation for each component:

- **[YAML frontmatter](../core/yaml-frontmatter.md)** - Schedules, workflows, and settings
- **[Core directives](../core/core-directives.md)** - File input/output, models, and tools (@input-file, @output-file, @model, @tools, etc.)
- **[Pattern variables](../core/patterns.md)** - Dynamic file names using {today}, {this-week}, etc.


