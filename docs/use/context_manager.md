# Context Manager (Chat Templates)

**⚠️ This is an experimental feature and may change significantly in the future!!**

Context templates control how chat history is curated and let you add user-provided system instructions to the chat agent (in addition to the app's built-in instructions). They live in `AssistantMD/ContextTemplates/` inside a vault (vault-specific) or `system/ContextTemplates/` (global). The chat UI lets you pick a template per session; vault templates override system templates with the same filename.

You can set a default template name in **Configuration → General Settings** via `default_context_template`. If the same filename exists in a vault, the vault template wins for that session.

Templates are regular markdown files with sections:
- `## Chat Instructions`: Passed directly to the chat agent as a system instruction. No context-manager LLM call required.
- `## Context Instructions`: Guidance for the context-manager LLM when it runs (summaries, focus, format).
- `## Template`: Extraction template plus any directives.

## Example: Chat Instructions Only

Use this when you want a custom system prompt but do not want the context manager to summarize or curate history.

```
---
description: Workflow creation helper without history curation.
---

## Chat Instructions
You are a workflow coach. Ask clarifying questions before writing anything.
Follow a four-step flow: discovery, deeper questions, plan recap, approval.
Only write files after the user says "yes".
```

With only `## Chat Instructions`, the chat agent receives the instructions and the full chat history is passed through (no context-manager LLM call).

## Example: Enable History Curation

Add context instructions, a template, and directives to run the context manager.

```
---
description: Keep the chat focused and summarize recent runs.
---

## Chat Instructions
Stay on topic and follow the user's goals. Ask concise follow-up questions.

## Context Instructions
Summarize the recent conversation using the template below.
Output should be short, structured, and actionable.

## Template
@recent-runs 2
@passthrough-runs all
@token-threshold 3000
@recent-summaries 1
@model gpt-mini

Include:
- mission
- constraints
- next_step
- recent_turns
```

## Directive Reference (Context Manager)

- `@recent-runs`: How many recent chat runs the manager reads (0 disables the manager).
- `@passthrough-runs`: How many runs the chat agent receives verbatim (`all` keeps full history, 0 yields summary-only when the manager is enabled).
- `@token-threshold`: Skip the manager if total history is under this token estimate.
- `@recent-summaries`: How many prior managed summaries to feed into the manager prompt.
- `@tools`: Tools the manager can call while generating the summary.
- `@model`: Model alias to use for the manager.
