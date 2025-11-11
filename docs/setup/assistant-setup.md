# Assistant Setup Guide

An assistant is a markdown file in a vault's `assistants/` folder that defines a scheduled AI workflow. Assistants can be in subfolders (one level deep) for better organization. Folders prefixed with underscore (e.g., `_chat-sessions`) are ignored.

Following is a complete and valid assistant file which you can use as a starting point. Copy and paste the text into a markdown file in your assistants folder and then Rescan from the Dashboard tab in the web UI to load it.

**NOTE**: Assistant files must include only the text below, not embedded inside a code block.

```
---
schedule: cron: 0 9 * * *
workflow: step
enabled: true
description: Daily learning assistant
---

## Instructions
You are a helpful learning assistant.

## Weekly plan
@run-on monday
@output-file lesson_plans/plan-{this-week}
@input-file goals.md
@model gpt-5

Review my goals and suggest a weekly learning plan. Keep it high level, focused on key topics and learning objectives.

## Daily reading
@output-file lesson_plans/daily-{today}
@input-file lesson_plans/plan-{this-week}
@model gpt-5
@tools web_search

Review my weekly learning plan and the morning notes I have added and then search the web to build a daily reading list. Keep it short, 2 or 3 links per day with a focus on quality and authoritative content.
```

**Structure**
YAML frontmatter between `---` delimiters (required). These appear as properties if using Obsidian.
Sets the run schedule using a cron expression and the workflow engine to run. Currently there is only one workflow engine: step.

`## INSTRUCTIONS` section with a prompt that is included as a system instruction before every step prompt. This section is optinal.

One or more `## Header` sections which define the steps to run. Steps run in the order they appear in the assistant file. The header name can be anything.

---

Explore detailed documentation for each component:

- **[YAML frontmatter](../core/yaml-frontmatter.md)** - Schedules, workflows, and settings
- **[Core directives](../core/core-directives.md)** - File input/output, models, and tools (@input-file, @output-file, @model, @tools, etc.)
- **[Pattern variables](../core/patterns.md)** - Dynamic file names using {today}, {this-week}, etc.


