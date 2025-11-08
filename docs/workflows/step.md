# Step Workflow

Multi-step AI workflows that execute steps in sequence. Each step can have different directives, models, and output files.

## Shared Foundation

This workflow uses all standard features:
- [YAML Frontmatter](../core/yaml-frontmatter.md)
- [Core Directives](../core/core-directives.md)
- [Pattern Reference](../core/patterns.md)

## Step-Specific Features

**@run-on directive**: Controls which days of the week a step executes
- Format: `@run-on monday, friday` or `@run-on daily` or `@run-on never`
- Default: Runs every day the assistant is scheduled

**Step execution**: Steps execute in file order, each processing its directives, getting AI instructions, and writing to the specified output file.

## Example Assistant

```markdown
---
schedule: cron: 0 8 * * *
workflow: step
enabled: true
description: Daily planning assistant that reviews goals and creates task lists
---

## INSTRUCTIONS

You are a helpful planning assistant. Be concise and actionable in your recommendations. Focus on practical next steps.

## STEP1
@run-on monday
@output-file planning/{this-week}
@input-file goals.md
@model sonnet

Review my goals and create a weekly plan focusing on key priorities.

## STEP2
@run-on monday, tuesday, wednesday, thursday, friday
@output-file tasks/{today}
@input-file planning/{this-week}
@tools web_search
@model gpt-4o

Based on the weekly plan, recommend 6 specific tasks to accomplish today. If any tasks require current information, search for recent updates.

## STEP3
@run-on friday
@output-file reviews/{this-week}
@input-file tasks/{latest:5}
@write-mode append

Review the week's task completion and provide insights for next week's planning.
```

This example demonstrates:
- **Weekly Planning** (Monday only): Reviews goals, creates weekly priorities
- **Daily Tasks** (Weekdays only): Creates specific daily task lists with web search
- **Weekly Review** (Friday only): Analyzes progress using recent task files
- **Multiple Models**: Different AI models for different task types
- **Organized Output**: Separate files for planning, tasks, and reviews
- **Pattern Variables**: Dynamic date-based file names
