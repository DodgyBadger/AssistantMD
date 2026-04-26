# Authoring: Workflow Scripts and Context Assembly Scripts

AssistantMD has a unified authoring surface for two types of automation: **workflow scripts** and **context assembly scripts**. Both are markdown files with a Python code block. Both live in `AssistantMD/Authoring/` inside your vault.

You don't need to write these files by hand. Describe what you want to the chat agent — it will draft, edit, and help you test authoring files. Use this document as orientation.

The common script pattern is: use tools and helpers for host-owned access to allowed capabilities like vault access, message history and web search; use ordinary Python to manipulate, filter, sort, and transform data; use the `delegate` tool when the script needs model inference.

---

## File Shape

Every authoring file follows the same structure: YAML frontmatter followed by exactly one fenced Python block.

````markdown
---
run_type: workflow
description: My automation
---

```python
# your code here
```
````

Rules:
- Exactly one ` ```python``` ` block. No more, no less.
- Scripts execute in a limited Python sandbox using Pydantic Monty.
- Details of the Monty execution environment, helper functions, and supported Python features can be found in [the runtime reference](../tools/code_execution.md). That document covers the shared helper surface used by chat-side `code_execution` and by authored workflow scripts and context scripts.

Files can be organized in subfolders one level deep inside `Authoring/`. Subfolders starting with `_` are ignored.

---

## Workflow Scripts

A workflow script is an automation that runs Python code against your vault. Use a workflow script when you want to:

- Generate or transform files on a schedule (daily notes, weekly summaries, reports)
- Process a batch of files (inbox triage, tagging, indexing)
- Chain multiple LLM calls with conditional logic

**Frontmatter for workflow scripts:**

```yaml
---
run_type: workflow
schedule: "cron: 0 9 * * 1"   # optional — omit for manual-only
enabled: false                  # true to activate scheduled runs
description: Weekly planning
week_start_day: monday          # optional, default monday
---
```

- `schedule` supports `cron: MINUTE HOUR DOM MONTH DOW` or `once: YYYY-MM-DD HH:MM`
- `enabled: false` pauses scheduled runs; manual runs always work
- Rescan your vault after changing `enabled` or `schedule`

---

## Context Assembly Script

A context assembly script shapes what the chat agent knows at the start of a conversation. Use a context script when you want to:

- Control which history the agent sees (curate, summarize, or filter prior turns)
- Load relevant files or skill listings into the agent's context automatically
- Build a specialized assistant mode for a particular project or workflow script

**Frontmatter for context scripts:**

```yaml
---
run_type: context
description: Regular chat with full history
---
```

Most context scripts use three core pieces: `retrieve_history()` to read completed prior session history, read-only `latest_message` to branch on the active message, and `assemble_context()` to hand the assembled context to the chat agent. `retrieve_history().items` counts safe units: user message = 1, assistant message = 1, matched tool call + return = 1. Do not append `latest_message` manually; the runtime adds it exactly once after the assembled context.

Select which script to use in the Chat UI. Set a default in **Configuration → Application Settings**.

Scripts are discovered from `AssistantMD/Authoring/` (vault) and `system/Authoring/` (global). Vault scripts take precedence. System seed scripts are refreshed on startup; copy one to a new vault script before customizing it.

### Customizing the default script with soul.md

For simple instruction customization — agent personality, response style, ground rules — you don't need to create a context script at all. Create `AssistantMD/soul.md` in your vault with plain text instructions:

```
You are a focused research assistant. Keep responses brief and factual.
Always cite the source file when referencing vault content.
Prefer bullet points over prose.
```

The default context script loads `soul.md` automatically if it exists and uses it as the system instruction. If no `soul.md` is present, a built-in default stance is used instead. The file is plain markdown — no frontmatter, no special syntax.
