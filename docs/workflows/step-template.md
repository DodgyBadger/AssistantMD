---
schedule: cron: 0 8 * * *
workflow: step
enabled: true
description: Daily planning assistant
---

## STEP1
@output-file planning/{today}
@input-file goals.md
@model sonnet

Review my goals and create today's plan with specific tasks.

## STEP2
@output-file tasks/{today}
@input-file planning/{today}
@tools web_search

Based on today's plan, create 6 specific actionable tasks. Search for any information needed to make tasks concrete and achievable.
