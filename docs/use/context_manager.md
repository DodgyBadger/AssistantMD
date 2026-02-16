# Context Manager

The Context Manager allows you to shape what the chat agent sees, from simple system‑prompt injection to multi‑step context assembly. It applies the lessons learned by research on long‑running agents: curated working sets, structured summaries and explicit attention budgeting beat dumping full transcripts into ever‑larger contexts.

Define context templates using markdown in `AssistantMD/ContextTemplates/` (vault scoped) or `system/ContextTemplates/` (global). Select the template you wish to use in the Chat UI. Set your default template in **Configuration → Application Settings**.

## Structure
YAML frontmatter between `---` delimiters. Settings that apply to the whole template.

`## Chat Instructions`: Custom system instructions passed through, unmodified, to the chat agent.

`## Context Instructions`: System instructions for the context manager LLM when it runs.

`## Step`: Any other `##` heading that does not include the word "instructions" is treated as a context manager step.
- Steps execute in the order they appear.
- Steps can be configured to output to the chat agent's context, generate information for later steps or write files to your vault.
- A step only outputs to the chat agent context if you include `@output context`.
- Context is not passed automatically between steps. Use `@output variable:foo` + `@input variable:foo` to pass context (or `file:name` if you want greater observability).
- Steps can be cached to minimize LLM calls.

The chat agent receives system instructions from the context manager in the following order:
- Hardcoded system instructions (date, tool descriptions, etc.)
- User-defined instructions in `## Chat Instructions`
- The output of each `## Step` section that includes `@output context`, in the order they appear

See [reference](reference.md) for details on all the control primitives available for context templates.

Following are complete, valid context manager templates. Copy the text into `AssistantMD/ContextTemplates/` inside any vault, change the model as needed, rescan your vaults and then start a new chat to test the results.

**NOTE**: Context templates must include only the text below, not embedded inside a markdown code block. If you are pasting into a new note in Obsidian, use `ctrl-shift-v` (or right-click `Paste as plain text`) to avoid pasting the code block. The top section should immediately render as Obsidian Properties.

## Example: Custom system instructions only

As simple as it gets - just a regular chat session with full history, unmodified, and a custom system instruction for the chat agent.

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
@recent_runs 3
@recent_summaries 1
@output context
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
