---
enabled: false
schedule: "cron: 10 0 * * *"
workflow_engine: step
week_start_day: monday
description: Summarize yesterday’s chat transcripts (by filename date stamp) into a running weekly memory log.
---

## Instructions
You maintain a lightweight, high-signal memory log based on chat transcripts.

Rules:
- Be concise. Prefer bullets over prose.
- Do not quote long passages.
- Focus on: decisions, commitments, preferences, unresolved tasks/questions, key artifacts/paths.
- Do not invent details.
- Each transcript summary MUST include the transcript path.

Output format (repeat per transcript):
- transcript: <vault-relative path>
- summary: <1-3 bullets>
- decisions: <bullets or N/A>
- open_loops: <bullets or N/A>
- preferences_facts: <bullets or N/A>

## Summarize yesterday chats
@model gpt-mini  
@input file: AssistantMD/Chat_Sessions/*_{yesterday:YYYYMMDD}_*.md (required)  
@output file: AssistantMD/Memory/Weekly/{this-week}  
@write_mode append  
@header Chat Memory — {yesterday}  

For each transcript provided, write one entry following the output format.