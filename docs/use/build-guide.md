# How to Build with Assistant.md

This guide introduces Assistant.md's main building blocks and how they can be combined:

- Skills
- Workflow scripts
- Context assembly scripts
- Session summaries

You can combine these to create behavior to suit your needs. Assistant.md ships with a default composition that can cover many needs by editing only a few Markdown files in your vault. Start by customizing the default composition before building your own from scratch.

The chat agent can help. Open a new chat session and ask the agent for guidance. It can clarify your goal and help you customize Assistant.md.

The default context assembly script looks for the following files:

- `AssistantMD/soul.md` for personality and response style.
- `AssistantMD/playbook.md` for global working policy: source-of-truth rules, review standards, file conventions, or recurring preferences.
- `AssistantMD/Skills/` for repeatable procedures.
- `{workspace}/README.md` for orientation to work being done in that folder.
- `{workspace}/playbook.md` for project-local policy that should be more specific than the global playbook.

The default composition also includes a nightly workflow to extract session summaries, making them available to the `session_ops` tool. After installation, enable the `system/nightly-session-summarization` workflow under **Dashboard → Workflows** if you want automatic summary extraction.

The default composition is also an example for building your own:

- [Default context script](../../core/authoring/seed_templates/context/default.md)
- [Nightly session-summarization workflow](../../core/authoring/seed_templates/workflows/nightly-session-summarization.md)

The rest of this guide explains the building blocks individually.

---

## Chat

Open the app, pick a model, and start talking. The chat agent can read, search, and write files in your vault using its built-in tools.

What you can do with zero setup:

- Ask the agent to find and summarize information across your notes
- Have it draft new documents based on existing material
- Organize, tag, or restructure files
- Research topics with web search and save findings to your vault

### Workspace folders

When starting or continuing a chat, you can set a workspace to a folder in the selected vault. Workspace does not restrict what the agent can access; it is a session-level hint that context assembly scripts can use to load local orientation files.

The default context assembly script uses two workspace conventions:

- `{workspace}/README.md` introduces the folder: what it is, current state, important files, active goals, or constraints.
- `{workspace}/playbook.md` adds workspace-specific working policy. It is loaded after `AssistantMD/playbook.md`.

Leave either file out when you do not need it. If you want only workspace-local working policy, omit `AssistantMD/playbook.md` and keep the local playbook in the workspace folder.

### Capability availability

Settings-backed built-in tools can be used by primary chat, delegates, and authored scripts when they are enabled and explicitly bound for that execution. Connection-backed built-ins add another readiness gate: for example, `gmail` is available only when the current user has a sufficiently scoped Google connection.

Configured network and stdio MCP tools, along with the general `shell` tool, are currently primary-chat capabilities. They cannot be declared in workflow or context scripts or passed to delegate children. Use ordinary built-in tools in authored automation, or have the user perform the MCP or advanced-shell step in primary chat.

---

## Skills

When you find yourself giving the same instructions repeatedly, or when a task needs a precise procedure, write a **skill file**.

A skill is a plain Markdown file describing a task. The built-in default script discovers skill files from both of these structures using `name` and `description` frontmatter:

- `AssistantMD/Skills/skill-name/SKILL.md`
- `AssistantMD/Skills/skill-name.md`

Assistant.md is not inherently opinionated about how skills are defined. The active context assembly script discovers skills, so a custom script can load them however you want. For example, you could bundle skills under each project folder and load only those relevant to the project.

A good skill gives the agent enough to work independently: the goal, relevant paths, procedure, output shape, and rules. Be concrete about where files live, what the task should produce, and what the agent should avoid changing.

---

## Workflow Scripts

Use a workflow script when a task must run on a schedule or needs more complexity or determinism than an LLM can reliably provide: strict sequencing, conditional logic, multi-step file routing, or cost control across steps.

Skills and workflow scripts can work together. A skill can instruct the agent to trigger a workflow as part of its procedure. A workflow can read a skill file and follow its instructions as one of its steps.

Reusable, discoverable, and scheduled workflow scripts live in `AssistantMD/Authoring/` with `run_type: workflow`. A workflow that belongs to a specific project can instead live beside that project's content anywhere in the vault. Run it explicitly with `workflow_run(operation="run", workflow_path="path/to/workflow.md")`, or use `operation="start"` for a background run. Project-local workflows must also declare `run_type: workflow`; they are not discovered, scheduled, enabled, or disabled automatically.

You don't need to write the Python yourself: describe what you want to the chat agent and it will draft the file for you. You can then run it manually, refine it, and enable scheduling when you're happy with it. Manual and scheduled runs are tracked as Dashboard tasks, so long-running workflows can be checked or cancelled without blocking the chat.

For the full authoring reference, see [Authoring](authoring.md).

---

## Context Assembly Script

A Context Assembly Script controls what the chat agent knows at the start of every conversation. It is the place where the other building blocks can come together: prior messages, selected files, user preferences, skills, project policy, and summary records. This is usually the least-used building block: most users can customize the default script with playbooks, skills, workspace README files, and workflows, and may only need one or two custom context scripts, if any, for clearly distinct work styles.

Context scripts live in `AssistantMD/Authoring/` with `run_type: context`.

Like workflow scripts, you don't need to write these by hand. Describe what you want to the chat agent and it will draft the file.

For the full authoring reference, see [Authoring](authoring.md).

---

## Session Summaries

Session summaries are derived records of prior chat sessions. They help the agent find related past work without reading entire transcripts. Assistant.md defines the summary fields that are extracted and the retrieval behavior used by `session_ops`, but it does not require session summaries to run at a particular time or be injected into chat context in a particular way. Those choices are part of your composition.

The default setup includes an optional workflow that can summarize chats over time, and the `session_ops` tool can search or refresh those summaries when prior-work recall is useful.

Session summary indexing requires a configured `embeddings` model alias. The current supported setup is the default OpenAI embedding model `text-embedding-3-small` with `OPENAI_API_KEY` configured in secrets. The nightly summarization workflow fails before extracting summaries when that embedding setup is unavailable, so failed runs do not leave incomplete session summary records behind.

---

## How pieces combine

The building blocks are meant to compose behavior.

- Create workflows that automate repetitive tasks, like watching a folder, classifying new files, and turning them into structured notes.
- Add quality gates that scan project folders for missing frontmatter, broken links, stale status fields, or required review notes.
- Load project-specific skills from the active workspace instead of using one global skills folder for every chat.
- Build a research desk that combines source-ingestion workflows, citation skills, workspace briefs, and session-summary recall.
- Experiment with your own memory system by overriding `AssistantMD/Skills/save_user_note.md`, compacting user notes with a workflow, or loading selected session summaries into context.
