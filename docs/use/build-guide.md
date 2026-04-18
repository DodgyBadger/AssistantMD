# How to Build with AssistantMD

This guide walks through AssistantMD's capabilities in order of complexity. Start at Level 1 and go as far as you need — each level builds on the previous one, but you don't need to reach Level 4 to get real value.

---

## Level 1: Chat

Open the app, pick a model, and start talking. The chat agent can read, search, and write files in your vault using its built-in tools.

**What you can do with zero setup:**
- Ask the agent to find and summarize information across your notes
- Have it draft new documents based on existing material
- Organize, tag, or restructure files
- Research topics with web search and save findings to your vault

---

## Level 2: Skills

When you find yourself giving the same instructions repeatedly, or when a task needs a precise procedure, write a **skill file**.

A skill is a plain markdown file describing a task in clear English. Put skills in `AssistantMD/Skills/`. The default context template scans that folder and injects a summary of available skills before every chat session — so when your request matches a skill, the agent reads and follows it automatically without you needing to name it explicitly.

AssistantMD's skill convention is similar to Anthropic's [skills protocol](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/skills-protocol): both use `name` and `description` frontmatter fields as the discovery surface. The difference is flexibility — you don't need to name files `skill.md` or organize them into per-skill subfolders. A single markdown file per skill is fine, and you can name and organize them however suits your vault.

### What makes a good skill

Include everything the agent needs to work independently:
- **Goal** — what the task produces
- **Paths** — exact vault-relative file locations
- **Procedure** — step-by-step
- **Rules** — what to avoid, edge cases, output format

### Example

```markdown
---
name: Weekly Note Summarizer
description: Summarize this week's project notes into a single brief.
---

## Goal
Create a concise summary of this week's project notes.

## Files
- Input: Projects/WeeklyNotes/
- Output: Projects/Summaries/weekly-summary.md

## Procedure
1. Read all markdown files in Projects/WeeklyNotes/
2. Extract key points and group by topic
3. Write the result to Projects/Summaries/weekly-summary.md
4. Report back with the file path and word count

## Rules
- Keep output under 300 words
- Include action items at the end
- Don't rewrite the file if it already exists this week
```

When you ask *"summarize my notes from this week"*, the agent recognizes the match, reads the skill file, and follows the procedure.

### Tips

- **Be specific about paths.** Vague references like "the output folder" cause errors.
- **Show the output format.** Don't describe it abstractly — show an example of what you want.
- **Include state management** for tasks that span multiple runs. A simple state file with a cursor works well.
- **Set limits.** Tell the agent what not to do. "Don't modify files outside this folder" prevents surprises.
- **Keep batch sizes reasonable.** For image-heavy or large-file tasks, tell the agent how much to process at a time.

---

## Level 3: Workflows

Use a workflow when you need a task to run on a schedule, or when the task requires a higher degree of complexity or determinism than a single agent pass can reliably deliver — strict sequencing, conditional logic, multi-step file routing, cost control across steps.

Skills and workflows can work together. A skill can instruct the agent to trigger a specific workflow as part of its procedure. A workflow can read a skill file and follow its instructions as one of its steps. Mix and match however makes sense for the task.

A workflow is a Python script in a markdown file, stored in `AssistantMD/Authoring/`. You don't need to write the Python yourself: describe what you want to the chat agent and it will draft the file for you.

### Creating a workflow

Ask the agent: *"Create a workflow that runs every Monday morning, reads my task list, extracts anything due this week, and writes it to a planning file."*

The agent will create a file in `AssistantMD/Authoring/` with the appropriate frontmatter and Python code. You can then run it manually to test, refine and enable scheduling when you're happy with it.

Key frontmatter fields:

```yaml
---
run_type: workflow
schedule: "cron: 0 9 * * 1"   # optional — omit for manual-only
enabled: false                  # set true to activate scheduled runs
description: Weekly planning
---
```

For the full authoring reference, see [Authoring](authoring.md).

---

## Level 4: Context templates

A context template controls what the chat agent knows at the start of every conversation. The default template already handles the common cases — skills catalog, full history — but you can go further.

### Customizing the agent's personality: soul.md

For simple customization — tone, response style, ground rules — you don't need to create a context template. Create `AssistantMD/soul.md` with plain text instructions:

```
You are a focused research assistant.
Keep responses brief and cite the source file when referencing vault content.
Prefer bullet points over prose.
Ask one clarifying question before starting any multi-step task.
```

The default template loads this file automatically and uses it as the agent's system instruction. Edit it whenever you want to adjust the agent's behavior.

### Custom context templates

For more control — curating history, loading specific files, summarizing prior conversations — create a context template in `AssistantMD/Authoring/` with `run_type: context`.

Like workflows, you don't need to write these by hand. Describe what you want to the agent and it will draft the file.

**Example use cases:**
- Summarize long conversation histories so the agent stays focused as chats grow
- Load project-specific files into context automatically when starting a session
- Build a specialized mode for a particular domain (coding assistant, research assistant, writing editor)

Select which template to use in the Chat UI. Set a default in **Configuration → Application Settings**.

See [Authoring](authoring.md) for the full context template reference.

---

## Quick start checklist

1. **Open the app** at `http://localhost:8000/`
2. **Configure a provider** in the Configuration tab
3. **Start chatting** — explore your vault, ask questions, create files
4. **Write a skill** — pick something repetitive, describe the procedure in `AssistantMD/Skills/`
5. **Test it in chat** — make a request that matches the skill and see if the agent picks it up
6. **Automate it** — ask the agent to wrap it in a workflow when you want it scheduled
7. **Customize the agent** — add `AssistantMD/soul.md` to set tone and ground rules
