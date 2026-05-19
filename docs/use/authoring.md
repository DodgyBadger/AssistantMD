# Authoring: Workflow Scripts and Context Assembly Scripts

AssistantMD has a unified authoring surface for two types of automation: **workflow scripts** and **context assembly scripts**. Both are markdown files with a Python code block. Both live in `AssistantMD/Authoring/` inside your vault.

You don't need to write these files by hand. Describe what you want to the chat agent — it will draft, edit, and help you test. Use this document as orientation.

The common script pattern is: use tools and helpers for host-owned access to allowed capabilities like vault access, message history and web search; use ordinary Python to manipulate, filter, sort, and transform data; use the `delegate` tool when the script needs model inference. When a task could be solved either by deterministic parsing or by model judgment, present both options to the user and ask which tradeoff they prefer. Parsing is cheaper and repeatable; delegation is often better for ambiguous extraction, summarization, classification, or judgment. Always pass `delegate` explicit instructions - never assume it knows anything about the environment including tool use.

When a delegated step gives odd results, inspect `result.metadata["audit"]` before changing the script blindly. The audit summarizes the child agent's tool calls, arguments, return previews, and tool errors, so you can tell whether the child used the intended tools, hit a file/tool problem, or produced a poor model answer.

For incremental file processing, first use `file_ops_safe(...)` to list, search, or otherwise select candidate files, then pass that result to `pending_files(operation="get", items=...)`. `pending_files` does not accept `path`, `pattern`, `glob`, or `search_term` directly. Each pending item can include `item.metadata["pending_diff"]`, which is the built-in diff from the last time the current workflow or chat scope completed that file to the current file. Prefer that metadata over maintaining separate copies or writing custom regex comparisons. After processing the selected items, call `pending_files(operation="complete", items=selected)` so the next run has a fresh baseline.

---

## File Shape

Every authoring file follows the same structure: YAML frontmatter followed by exactly one fenced Python block.

````markdown
---
run_type: workflow | context
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
- Start with the simplest script that can do the job, test it, then add complexity only when the result proves it is needed.
- Always include comments to help the user understand the script
- Always define variables that the user might want to edit at the top of the script: file paths, titles, prompts, model, thinking, etc.

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

Workflows can use `retrieve_sessions(selection="pending_or_stale_memory")` to select current-vault chat sessions that do not yet have derived memory or whose memory is stale. It returns session metadata only; use `retrieve_history()` or `memory_ops` when a workflow needs to process a specific session. Stale selection respects the `stale_memory_min_new_messages` general setting.

Select which script to use in the Chat UI. Set a default in **Configuration → Application Settings**.

Scripts are discovered from `AssistantMD/Authoring/` (vault) and `system/Authoring/` (global). Vault scripts take precedence. Startup creates missing system seed scripts, and **System → Misc** can refresh existing system seed scripts from packaged defaults.
