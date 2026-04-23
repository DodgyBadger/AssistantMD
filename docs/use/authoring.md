# Authoring: Workflows and Context Templates

AssistantMD has a unified authoring surface for two types of automation: **workflows** and **context assembly**. Both are markdown files with a Python code block. Both live in `AssistantMD/Authoring/` inside your vault.

You don't need to write these files by hand. Describe what you want to the chat agent — it will draft, edit, and help you test authoring files. Use this document as orientation.

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
- Details of the Monty execution environment, helper functions, and supported Python features can be found in [the runtime reference](../tools/code_execution_local.md). That document covers the shared helper surface used by chat-side `code_execution_local` and by authored workflows/context templates.

Files can be organized in subfolders one level deep inside `Authoring/`. Subfolders starting with `_` are ignored.

---

## Workflows

A workflow is an automation that runs Python code against your vault. Use a workflow when you want to:

- Generate or transform files on a schedule (daily notes, weekly summaries, reports)
- Process a batch of files (inbox triage, tagging, indexing)
- Chain multiple LLM calls with conditional logic

**Frontmatter for workflows:**

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

## Context assembly

A context assembly script shapes what the chat agent knows at the start of a conversation. Use a context assembly script when you want to:

- Control which history the agent sees (curate, summarize, or filter prior turns)
- Load relevant files or skill listings into the agent's context automatically
- Build a specialized assistant mode for a particular project or workflow

**Frontmatter for context assembly scripts:**

```yaml
---
run_type: context
description: Regular chat with full history
---
```

The Python block retrieves session history and calls `assemble_context()` to hand the assembled context to the chat agent.

Select which script to use in the Chat UI. Set a default in **Configuration → Application Settings**.

Scripts are discovered from `AssistantMD/Authoring/` (vault) and `system/Authoring/` (global). Vault scripts take precedence.

### Customizing the default script with soul.md

For simple instruction customization — agent personality, response style, ground rules — you don't need to create a context assembly script at all. Create `AssistantMD/soul.md` in your vault with plain text instructions:

```
You are a focused research assistant. Keep responses brief and factual.
Always cite the source file when referencing vault content.
Prefer bullet points over prose.
```

The default context assembly script loads `soul.md` automatically if it exists and uses it as the system instruction. If no `soul.md` is present, a built-in default stance is used instead. The file is plain markdown — no frontmatter, no special syntax.

---

## Authoring Loop

1. **Describe** what you want to the chat agent — "create a workflow that reads my inbox folder, summarizes each new note, and appends the summary to a log file"
2. **The agent drafts** the file and places it in `AssistantMD/Authoring/`
3. **Compile** using the workflow UI to catch syntax errors before running
4. **Run manually** to test; check the output
5. **Iterate** — ask the agent to adjust until it behaves correctly
6. Add `schedule:` and set `enabled: true` when ready to automate

For capability signatures and return types, the agent can inspect the runtime contract directly. Ask it to check `__virtual_docs__/tools/code_execution_local.md` when it needs the Monty helper API details.
