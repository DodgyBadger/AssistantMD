---
passthrough_runs: all
description: Pass summary of available skills to the chat agent.
---

## Chat Instructions
The following skills are available to help you fulfill the user's request. Select what seems most appropriate and then read the full skill at the path provided.

## Skill Index
@recent_runs 0
@recent_summaries 0
@input file: AssistantMD/Skills/*.md
@output context
@header Available skills
@model gpt-mini
@cache 1d

Create a concise list of the available skills in the following format:

**Skill name**
One or two sentences describing the skill's purpose.
Read full details at: file_path

