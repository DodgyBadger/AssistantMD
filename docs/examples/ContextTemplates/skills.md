---
passthrough_runs: all
description: Index skills and select the best one for the current chat.
---

## Chat Instructions
Use the selected skill to guide your response.

## Skill Index
@recent-runs 0
@recent-summaries 0
@input file: skills/*.md
@output context
@model gpt-mini

Create a concise list of the available skills with:
- skill name
- one-line purpose
- file path

## Skill Selection
@recent-runs 5
@recent-summaries 2
@input file: skills/*.md
@output context
@model gpt-mini

Pick the single best skill that will help the chat agent complete the user's task or mission.
Output only the skill content to be injected into the chat agent.
If there is no clear task or mission, output: "skill: not required".
If there is a clear task but no clear matching skill, output: "skill: no matching".