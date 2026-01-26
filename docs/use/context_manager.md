# Context Manager (Chat Templates)

**⚠️ This is an experimental feature and may change significantly in the future!!**

Define context templates using markdown in `AssistantMD/ContextTemplates/` (vault scoped) or `system/ContextTemplates/` (global). Context templates allow you to steer chat sessions by customizing the system instructions and chat history that is passed to the primary chat agent. Select the template you wish to use in the Chat UI. Set your default template in **Configuration → Application Settings**.

## Structure
- YAML frontmatter between `---` delimiters. Settings that apply to the whole template.
- `## Chat Instructions`: Custom system instructions passed through, unmodified, to the chat agent.
- `## Context Instructions`: System instructions for the context manager LLM when it runs.
- `## Step`: Any other `##` heading that does not include the word "instructions" is treated as a context manager step. The output of each step is passed to the chat agent as a system instruction. This section can include directives (see below) followed by a prompt for the context manager LLM.

Only `## Chat Instructions` and `## Context Instructions` are supported. Other headings containing "instructions" are ignored and will not run as steps.

The chat agent receives system instructions from the context manager in the following order:
- Hardcoded system instructions (date, tool descriptions, etc.)
- User-defined instructions in `## Chat Instructions`
- The output of each additional `## Step` section, in the order they appear

## YAML frontmatter

**week_start_day**
- same behaviour as [workflow frontmatter](frontmatter.md)

**passthrough_runs**
- How many runs (before the latest user message) are passed through to the chat agent. Can be any value >=0, or `all` for full history.
- The latest user message is always passed to the chat agent verbatim.

**token_threshold**
- Only run the context manager when estimated history tokens exceed this threshold.
- When below the threshold, the full passthrough history is sent and no context manager steps run.

**description**
- Human-readable description of what this template does
- For user documentation only. Has no functional impact on the template.

## Directives
**@recent-runs**
- Number of recent chat runs (roughly user-agent message turns but can include tool call or subagent messages), starting from the latest and moving backward, made available to this step for action in your prompt. Can be any value >=0, or `all` for full history.

**@recent-summaries**
- Number of prior context manager outputs (all steps treated as a single output) made available to this step for action in your prompt. Can be any value >=0, or `all` for all prior outputs.

**@input-file**
- File contents are included as additional context for the step
- Same syntax and options as [workflow directives](directives.md)

**@tools**
- Enables tools for the step, allowing the AI to perform actions beyond text generation
- Same syntax and options as [workflow directives](directives.md)

**@model**
- Specifies which AI model to use for this step. If omitted, defaults to the chat model.
- Same syntax and options as [workflow directives](directives.md)

**@cache**
- Caches the output of a step for reuse to avoid another LLM call when it is not needed
- Possible values:
  - session: cache only for the current chat session
  - daily: cache until the start of the next day (12:00am)
  - weekly: cache until the start of the next week (12:00am Monday, unless redefined by week_start_day)
  - duration in s, m, h, d (e.g. 30s, 10m, 2h, 1d)
- Regardless of the value, cache will expire if the template is edited
- Any directives which gate whether the step runs will override the cache, meaning you won't get a cached output when you don't expect any output.

## Example: Custom system instructions only

As simple as it gets - just a regular chat session with full history, unmodified, and a custom system instruction.

```
---
passthrough_runs: all
description: Regular chat session, full history, custom instructions.
---

## Chat Instructions
You are a helpful assistant. Keep your answers brief.
Get to the point and skip user flattery.
```

## Example: History curation

Single step chat history summarization to maintain focus on a mission.

```
---
passthrough_runs: 3
token_threshold: 4000
description: Keep the chat focused and summarize recent runs.
---

## Chat Instructions
Stay on topic and follow the user's goals. Ask concise follow-up questions.

## Context Instructions
Summarize the recent conversation using the extraction template below.

**Rules for responding**
- Follow the extraction template exactly. Do not add commentary or content not defined in the template.
- Base your extraction only on the chat history provided. Do not include details of this prompt.
- Do not invent content. Everything you output must be sourced from the chat history.
- If a field or instruction in the extraction template is not relevant, you must still include the field but with a value "N/A".

## Summary
@recent-runs 3
@recent-summaries 1
@model gpt-mini

Stick to the mission unless the user explicitly redefines it. Preserve the core topic and constraints even when the latest turn is a tangent. If you detect that you are on a tangent, include the following in chat_agent_instructions:
"Note: It looks like we are on a tangent from our original mission.
If you would like to change the topic, please say so explicitly and I will pivot."

What to include:
- **mission**: current mission/topic. Do not change unless the user explicitly redefines it.
- **constraints**: non-negotiable rules/formatting/scope. Preserve prior constraints unless explicitly changed.
- **plan**: next short step in service of the mission.
- **recent_turns**: the last few conversation snippets, succinct.
- **tool_results**: relevant tool outputs still in force.
- **reflections**: brief observations/adjustments if applicable.
- **latest_input**: the latest user message, concisely restated.
- **chat_agent_instructions**: Instructions to pass to the primary chat agent that is interacting directly with the user.

Format as compact bullet points under clear headings.
```

## Example: Two-step synthesis with files and chat

First step summarizes files without any chat history. Second step uses recent chat history and ties it back to the file summary.

```
---
passthrough_runs: all
description: Summarize research notes, then relate the latest chat to them.
---

## Chat Instructions
Stay concise and practical.

## File Summary
@recent-runs 0
@recent-summaries 0
@input-file research/*.md
@model gpt-mini

Summarize the key themes and notable facts across the files above.
Include short bullet points and cite file names when relevant.

## Chat Alignment
@recent-runs 3
@recent-summaries 1
@model gpt-mini

Relate the latest chat turns to the file summary above.
Call out conflicts, missing info, and next steps.
```

## Example: Skill selection from a folder

First step indexes available skills from a folder. Second step picks the best skill for the latest chat and injects its content.

```
---
passthrough_runs: all
description: Index skills and select the best one for the current chat.
---

## Chat Instructions
Use the selected skill to guide your response.

## Skill Index
@recent-runs 0
@recent-summaries 0
@input-file skills/*.md
@model gpt-mini

Create a concise list of the available skills with:
- skill name
- one-line purpose
- file path

## Skill Selection
@recent-runs 5
@recent-summaries 2
@input-file skills/*.md
@model gpt-mini

Pick the single best skill that will help the chat agent complete the user's task or mission.
Output only the skill content to be injected into the chat agent.
If there is no clear task or mission, output: "skill: not required".
If there is a clear task but no clear matching skill, output: "skill: no matching".
```
