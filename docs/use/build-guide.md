# How to Build with AssistantMD

This guide introduces AssistantMD's main building blocks and how they can be
combined. You can use any one of them on its own, but the system becomes more
useful when chat, skills, workflows, context assembly, and long-term context
patterns work together. The default setup AssistantMD ships with is one
practical example of that composition, and the sections below use it to show
how the pieces can fit.

Start by customizing the default setup before building your own composition
from scratch. You can usually get far by editing the shipped markdown
instructions, skills, and workflows, then replacing pieces only when the
default shape no longer fits.

---

## Chat

Open the app, pick a model, and start talking. The chat agent can read, search, and write files in your vault using its built-in tools.

**What you can do with zero setup:**
- Ask the agent to find and summarize information across your notes
- Have it draft new documents based on existing material
- Organize, tag, or restructure files
- Research topics with web search and save findings to your vault

---

## Skills

When you find yourself giving the same instructions repeatedly, or when a task needs a precise procedure, write a **skill file**.

A skill is a plain markdown file describing a task in clear English. The built-in default script will discover skill files from both of the following structures using `name` and `description` frontmatter as the discovery surface:
- `AssistantMD/Skills/skill-name/SKILL.md`
- `AssistantMD/Skills/skill-name.md`

AssistantMD is not inherently opinionated about how skills are defined. Skills are discovered by the active context assembly script, so a custom script can load them however you want. For example, you could bundle skills under each project folder and then load only those that are relevant to the project.

A good skill gives the agent enough to work independently: the goal, relevant
paths, procedure, output shape, and rules. Be concrete about where files live,
what the task should produce, and what the agent should avoid changing.

---

## Workflow Scripts

Use a workflow script when you need a task to run on a schedule, or when the task requires a higher degree of complexity or determinism than an LLM can reliably deliver — strict sequencing, conditional logic, multi-step file routing, cost control across steps.

Skills and workflow scripts can work together. A skill can instruct the agent to trigger a specific workflow script as part of its procedure. A workflow script can read a skill file and follow its instructions as one of its steps. Mix and match however makes sense for the task.

You don't need to write the Python yourself: describe what you want to the chat
agent and it will draft the file for you. You can then run it manually, refine
it, and enable scheduling when you're happy with it. Manual and scheduled runs
are tracked as Dashboard tasks, so long-running workflows can be checked or
cancelled without blocking the chat.

For the full authoring reference, see [Authoring](authoring.md).

---

## Context Assembly Script

A Context Assembly Script controls what the chat agent knows at the start of
every conversation. It is the place where the other building blocks can come
together: prior messages, selected files, user preferences, skills, project
policy, and summary records.

For more control — curating message history, loading specific files, searching
session summaries, or adding different long-term notes — create a context script
in `AssistantMD/Authoring/` with `run_type: context`.

Like workflow scripts, you don't need to write these by hand. Describe what you
want to the chat agent and it will draft the file. See
[Authoring](authoring.md) for script shape, helper functions, scheduling, and
runtime details.

---

## Session Summaries

Session summaries are derived records of prior chat sessions. They help the
agent find related past work without requiring entire transcripts by default.
AssistantMD defines the summary fields that are extracted and the retrieval
behavior used by `session_ops`, but it does not require session summaries to
run at a particular time or be injected into chat context in a particular way.
Those choices are part of your composition.

The default setup includes an optional workflow that can summarize chats over
time, and the `session_ops` tool can search or refresh those summaries when
prior-work recall is useful.

---

## How pieces combine

The building blocks are meant to compose. For example, a skill can define how to
triage new notes, a workflow can run that procedure every week, and a context
script can load the resulting planning note into future chats. Another setup
might use a skill to save durable user preferences, a workflow to compact those
notes over time, and session summaries to find related prior work.

---

## Customizing the default setup

AssistantMD ships with a default setup that is meant to be useful as-is and to
serve as an example of the composable style. Treat it as the recommended
starting point: inspect the pieces it loads, edit the ones that are close to
what you want, and build a new composition only when changing the default would
be harder than replacing it.

The default context assembly script (found in `system/Authoring/default.md`):
- Loads `AssistantMD/soul.md` and `AssistantMD/playbook.md` as additional system instructions.
- Discovers skills from `AssistantMD/Skills/`.
- Packaged skills include authoring instructions and a skill for maintaining a
  lightweight user-owned markdown note file.
- `session_ops` provides operations for searching and summarizing prior sessions.
- Packaged workflows, disabled by default, summarize chat sessions and maintain user notes.

This is a working default composition made from the same parts you can edit,
replace, or reuse in your own setup. Most customization happens in
user-owned markdown files, skills, workflows, and context scripts; you should
not need to change application code to change how your vault behaves.

For simple personality customization, create `AssistantMD/soul.md` with plain text instructions:

```
You are a focused research assistant.
Keep responses brief and cite the source file when referencing vault content.
Prefer bullet points over prose.
Ask one clarifying question before starting any multi-step task.
```

The default context assembly script loads this file automatically and uses it as the agent's system instruction. Edit it whenever you want to adjust the agent's behavior.

Use `AssistantMD/playbook.md` for working policy that is less about personality
and more about how the agent should approach your vault: when to search prior
work, how to treat project notes, what sources are authoritative, or what
review steps matter before changing files. The default context assembly script
loads it alongside `soul.md` when present.

### Long-term context as composition

AssistantMD does not require one built-in long-term memory system. The default
setup uses two complementary patterns as examples:

- User-approved markdown notes for durable facts and preferences.
- Derived session summaries for recall and search across prior chats.

To customize explicit "remember this" behavior, edit the shipped context-note
skill in `AssistantMD/Skills/`. That skill should define when a note is worth
saving, where the note is stored, how it is structured, and what should be
rejected or merged instead of appended. The default context script can stay
simple: it only needs to load the configured note file and expose the skill so
the chat agent knows how to maintain it.

For a more advanced customization, edit the packaged workflows. The shipped
workflows are global, disabled by default, and run across all mounted vaults
when enabled. Enable the nightly session summary workflow if you want
prior sessions summarized automatically over time; you can still customize when
it runs, batch size, model, and the surrounding policy in the script itself.
Enable or revise the context-note compaction workflow when you want the
context-note file maintained automatically according to the policy in the
context-note skill.
