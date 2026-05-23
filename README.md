# AssistantMD

> [!WARNING]
> **v0.6.0 introduces a major change that breaks all existing automations. See the [release notes](RELEASE_NOTES.md) for details. Pin your docker compose file to v0.5.0 (ghcr.io/dodgybadger/assistantmd:v0.5.0) if you are not ready to migrate.**

AssistantMD turns a folder of markdown files into an agent work surface.

You choose the folders the app can see. The chat agent can read, search, write,
summarize, and organize those files; follow reusable skills; run scheduled
workflow scripts; and carry context forward through markdown notes and session
summaries. The source of truth stays in plain text, so it remains easy to open
in Obsidian or any editor, version, back up, sync, inspect, and change.

AssistantMD is not trying to replace your markdown editor. It is a harness built
for that environment: a chat UI, tool layer, authoring system, and automation
runtime for working against a controlled vault of files.

AssistantMD works well with personal knowledge management, but it is not only a
"second brain" add-on. The stronger pattern is to start with the work you want
to do, then shape a markdown workspace around that goal: source material,
procedures, drafts, project state, review notes, and automation scripts. The
vault becomes the foundation of a work system, not just a place to store things
you might want to remember later.

- **Markdown-first work surface:** Your notes, drafts, procedures, and outputs
  live in plain text.
- **Controlled file access:** The agent works inside the mounted vaults you
  choose, not your whole machine.
- **Composable by design:** Chat, skills, workflows, context assembly, and
  long-term recall can be used independently or combined, with skills, scripts,
  policy, and context living beside your notes.
- **Cautious automation:** Built with prompt-injection awareness, Docker-based
  isolation, and constrained tool access instead of general shell access by default.

> **Security note:** AssistantMD has **no built-in auth or TLS**. Run it on a trusted network and/or add your own security layers. See [docs/setup/security.md](docs/setup/security.md).

## The Work Surface

When you run AssistantMD, it adds an `AssistantMD/` folder to each mounted vault:

- `AssistantMD/Skills/` — reusable procedures the agent can follow
- `AssistantMD/Authoring/` — workflow and context assembly scripts
- `AssistantMD/Chat_Sessions/` — exported chat transcripts
- `AssistantMD/Import/` — drop PDFs and images here to import to markdown

The default setup also looks for optional files such as
`AssistantMD/soul.md`, `AssistantMD/playbook.md`, and
`AssistantMD/context_notes.md`.

### Chat

Use chat when you want the agent to work directly against your vault: answer
questions from your notes, reorganize files, draft from existing material, or
research something and save the result.

### Skills

Skills are markdown procedures. Use them when you want the agent to follow the
same process every time: meeting prep, literature review, inbox triage, source
evaluation, or report drafting.

### Workflow Scripts

Workflow scripts are Python stored in markdown files. Use them when work should
run on a schedule or needs predictable sequencing: scan new notes, prepare a
weekly review, summarize stale sessions, or maintain context notes.

### Context Assembly

A context assembly script controls what the chat agent knows at the start of
each session: history, files, skills, instructions, policies, context notes,
and recall hooks.

### Long-term Context and Recall

AssistantMD does not impose one fixed memory model. The default setup uses two
complementary patterns: user-owned markdown context notes for explicit durable
facts and preferences, and session summaries for recall across prior chats.
Session summaries are searched through `session_ops`; enable or customize the
packaged nightly session summary workflow when you want them maintained
automatically.

## Things you could build

- A research vault where web findings, source extracts, drafts, and final
  reports stay linked and reusable.
- A client or project workspace that can generate meeting briefs from notes,
  decisions, open questions, and commitments already in the vault.
- A study system that turns imported PDFs, class notes, and reading lists into
  summaries, comparison tables, and review material.
- A lightweight business or personal operating system with daily notes,
  planning files, weekly reviews, and scheduled maintenance workflows.
- An R&D notebook where experiments, hypotheses, failures, and decisions are
  searchable across future chats.
- A repeatable writing pipeline where rough notes become outlines, drafts,
  edits, and publication checklists without leaving markdown.

## Documentation

- **[Installation Guide](docs/setup/installation.md)**
- **[Build Guide](docs/use/build-guide.md)** — start here for the composable building blocks and default setup
- **[Authoring Reference](docs/use/authoring.md)** — workflow scripts and context assembly scripts
- **[Security Considerations](docs/setup/security.md)**
- **[Upgrading](docs/setup/upgrading.md)**


## Requirements

- Docker Engine or Docker Desktop
- At least one LLM API key (OpenAI / Anthropic / Google / etc.) or an OpenAI-compatible API endpoint
- Comfort with the terminal


## License

MIT — see [LICENSE](LICENSE).


## Attributions

Some design ideas in AssistantMD were shaped by the work of others:

- **RLM-style research loops**: https://alexzhang13.github.io/blog/2025/rlm/
- Third-party software notices: see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
