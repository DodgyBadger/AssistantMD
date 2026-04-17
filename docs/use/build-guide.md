# How to Build with AssistantMD

This guide teaches you how to build AI-powered automations in AssistantMD. It starts simple and adds complexity only when needed.

## The key idea

AssistantMD is a markdown-native AI system. You chat with an AI agent that can read and write files in your vault. You can also schedule automated workflows. Both the chat agent and workflows are controlled by markdown files.

The most important thing to understand is that **you don't need to learn a complex system to do powerful things**. Start with what you already know: writing clear instructions in plain English.

---

## Level 1: Chat

Open the app, pick a model, and start talking. The chat agent can search, read, and create files in your vault using its built-in tools. This is already useful for research, writing, organizing notes, and working with your existing files.

**What you can do right now, with zero setup:**
- Ask the agent to find and summarize information across your notes
- Have it draft new documents based on existing material
- Ask it to organize, tag, or restructure files
- Research topics using web search and save findings to your vault

---

## Level 2: Skills

When you find yourself repeating the same kind of request, or when a task needs careful step-by-step procedure, write a **skill file**.

A skill is just a markdown file that describes a procedure in plain English. Think of it as a detailed instruction sheet you'd hand to a capable assistant. Put skills in `AssistantMD/Skills/` (or anywhere you like — it's just a file).

### What makes a good skill file

A skill file should contain everything the agent needs to execute the task independently:
- **What** to do (the goal)
- **Where** the files are (specific paths)
- **How** to do it (step-by-step procedure)
- **Rules** and constraints (what to avoid, edge cases)
- **Output format** (exactly what the result should look like)

### Example: Minimal skill file

```
---
title: Notes Summarizer
description: Summarize all notes in a folder into one weekly brief.
---

## Purpose
Create a concise summary of this week's project notes.

## Files
- Input folder: Projects/WeeklyNotes/
- Output file: Projects/Summaries/weekly-summary.md

## Rules
- Keep output under 300 words
- Group by topic
- Include action items at the end

## Procedure
1. Read all markdown files in `Projects/WeeklyNotes/`
2. Extract key points and group them by topic
3. Write the result to `Projects/Summaries/weekly-summary.md`
4. Return a short completion note with file path and word count
```

**How to use it**: In chat, say *"Load Notes Summarizer and run it."* The agent reads the skill file, follows the steps, writes the output file, and reports back.

Notice what this skill file does **not** contain: no special syntax, no directives, no DSL. It's just clear English that tells the agent what to do. Any capable LLM can follow it, and any human can read and edit it.

For a full production-style example (stateful, batch-based, image-heavy), see [Textbook Lesson Indexer](../examples/Skills/textbook_lesson_indexer.md).

### Tips for writing skills

- **Be specific about paths.** Vague references like "the output folder" cause errors. Use exact vault-relative paths.
- **Define formats explicitly.** Show the exact structure you want, don't describe it abstractly.
- **Include state management** if the task spans multiple runs. A simple state file with a cursor or counter works well (as in the textbook example).
- **Set boundaries.** Tell the agent what *not* to do. "Don't rewrite existing entries" prevents subtle regressions.
- **Keep batch sizes reasonable.** For image-heavy tasks especially, tell the agent how much to process at a time.

---

## Level 3: Wiring skills into your system

Once you have skills, there are two ways to make them more accessible.

### Option A: Skill-aware context template

A context template shapes what the chat agent knows before you even type your first message. You can create one that automatically loads a summary of all your available skills:

```
---
passthrough_runs: all
description: Pass summary of available skills to the chat agent.
---

## Chat Instructions
The following skills are available to help you fulfill the user's request.
Select what seems most appropriate and then read the full skill at the path provided.

## Skills
@input file: AssistantMD/Skills/* (output=context, properties="name,description")
@model none
```

With this template active, the chat agent already knows what skills exist and can load the right one when your request matches. You just describe what you want and the agent picks the skill.

The `@model none` means this step doesn't call an LLM — it just reads the frontmatter properties from your skill files and passes them into the chat context. The `properties` parameter means it only reads the name and description, not the full skill content, keeping the context window lean.

### Option B: Scheduled workflow

If you want a skill to run automatically (or in the background while you do other things), wrap it in a minimal workflow:

```
---
schedule: "cron: */10 * * * *"
run_type: workflow
enabled: false
description: Run the textbook indexer skill every 10 minutes
---

## Instructions
You are a workflow step runner. Follow the skill procedure and produce a concise result.

## Run textbook indexer
@input file: AssistantMD/Skills/textbook_lesson_indexer.md
@model gpt-mini
@tools file_ops_safe, file_ops_unsafe

Run the next batch. Report success or failure when done.
```

That's the entire workflow. One step, one skill, one model, and a one-line prompt.
- Use a schedule for ongoing jobs.
- Skip the schedule and run manually for finite jobs.
- Keep task logic in the skill file, not in the workflow wrapper.

---

## Level 4: Structured workflows

Sometimes the agentic skill approach isn't enough:

- **Smaller or local models** that need rigid boundaries and can't reliably follow multi-step procedures
- **Tasks that are too complex** for a single agent pass and need to be broken into stages
- **Deterministic pipelines** where you need guaranteed structure — specific files read, specific outputs written, strict sequencing
- **Cost or token control** where you want cheaper models for simple steps and more capable models only where needed

When you hit these cases, AssistantMD's workflow directives let you break things down into explicit steps with clear inputs, outputs, and constraints.

### Anatomy of a structured workflow

```
---
schedule: "cron: 0 6 * * *"
run_type: workflow
enabled: false
week_start_day: monday
description: Weekly task planning
---

## Instructions
You are a planning assistant. Output format: markdown, one bullet per task, keep it brief.

## Due this week
@model gpt
@input file: Planner/Master task list
@output file: Planner/Journal/{this-week}
@header Due this week

Review the master task list and list any tasks due this week.

## Carry-overs
@model gpt-mini
@input file: Planner/Journal/{last-week}
@output file: Planner/Journal/{this-week}
@header Carried over from last week

Review last week's journal and list items not completed that should carry over.

## Weekly summary
@run_on saturday
@model gpt
@input file: Planner/Journal/{this-week}
@output file: Planner/Journal/{this-week}
@header Tasks to carry to next week

Review this week's journal and list incomplete tasks to carry over.
```

Here each step is isolated: its own input, output, model, and prompt. The system handles file routing, date patterns, and scheduling. The LLM in each step has a narrow, well-defined job.

### When to use each directive

| Directive | What it does | When you need it |
|---|---|---|
| `@input file:` | Read a file into the step | When the step needs specific file content as context |
| `@output file:` | Write the step's response to a file | When the step should produce a file in your vault |
| `@model` | Choose which LLM runs this step | When different steps need different models (cost/capability) |
| `@tools` | Give the step access to tools | When the step needs to search, read, or write files dynamically |
| `@header` | Add a heading to the output file | When appending multiple step outputs to the same file |
| `@write_mode` | Control how output files are written | `append` (default), `replace`, or `new` (numbered files) |
| `@run_on` | Limit which days a step runs | When some steps should only run on certain days |
| `@input variable:` / `@output variable:` | Pass data between steps in memory | When one step needs another step's output but you don't want an intermediate file |

For the full directive reference including all parameters, patterns like `{today}`, selector modes like `pending/latest` on `@input`, and advanced features like routing and buffering, see the [Reference](reference.md).

---

## Choosing your approach

**The rule of thumb:** Start with skills. Move to structured workflows when the agent can't reliably handle the task in a single pass, or when you need guarantees about exactly what gets read and written. Most tasks — even complex ones like indexing a 600-page textbook — work well as skills.

---

## Context templates: shaping the chat agent

Context templates control what the chat agent sees and knows. They range from simple to sophisticated.

### Simple: Custom instructions only

```
---
passthrough_runs: all
description: Regular chat with custom personality.
---

## Chat Instructions
You are a helpful assistant. Keep your answers brief.
Get to the point and skip flattery.
```

This just adds a system instruction. Full chat history is passed through (`passthrough_runs: all`). No LLM processing of context.

### Intermediate: Skill-aware chat

Use the skills context template from Level 3A. The agent automatically knows what skills are available.

### Advanced: History curation

For long-running conversations, the context window fills up. Instead of dumping the entire transcript, you can have a separate LLM summarize the conversation and pass a curated summary to the chat agent:

```
---
passthrough_runs: 3
token_threshold: 4000
description: Summarize history to maintain focus.
---

## Chat Instructions
Stay on topic and follow the user's goals.

## Context Instructions
Summarize the recent conversation using the extraction template below.
Follow the template exactly. Do not add commentary.

## Summary
@recent_runs 3
@recent_summaries 1
@output context
@model gpt-mini

Extract from the conversation:
- **mission**: current topic (don't change unless user explicitly redefines it)
- **constraints**: rules/formatting/scope from the user
- **plan**: next short step
- **recent_turns**: last few exchanges, succinct
- **open_loops**: unresolved questions or tasks
```

This only activates when the conversation exceeds `token_threshold` (4000 tokens). Below that, the full history passes through. Above it, the context manager summarizes and passes the last 3 raw exchanges plus a structured summary.

### Key context template concepts

| Setting | What it does |
|---|---|
| `passthrough_runs: N` | How many recent exchanges pass through verbatim to the chat agent |
| `token_threshold` | Don't run context manager steps until history exceeds this size |
| `@output context` | Send this step's output into the chat agent's context |
| `@recent_runs N` | How many recent exchanges the context manager step can see |
| `@recent_summaries N` | How many prior context manager summaries to include |
| `@cache` | Cache step output to avoid repeated LLM calls (`session`, `daily`, `weekly`, or duration) |
| `@model none` | Skip the LLM — just route inputs directly (useful for injecting file content) |

---

## Quick start checklist

1. **Open the app** at `http://localhost:8000/`
2. **Configure a provider** (API key) in the Configuration tab
3. **Start chatting** — explore your vault, ask questions, create files
4. **Write your first skill** — pick a repetitive task you do, describe the procedure in `AssistantMD/Skills/`
5. **Test the skill in chat** — ask the agent to load and follow it
6. **Optionally schedule it** — wrap the skill in a minimal workflow when you want it automated
7. **Explore context templates** — start with custom instructions, add skills awareness, then try history curation as conversations get longer
