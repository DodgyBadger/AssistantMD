# AssistantMD

> [!WARNING]
> **v0.6.0 introduces a major change that breaks all existing automations. See the [release notes](RELEASE_NOTES.md) for details. Pin your docker compose file to v0.5.0 (ghcr.io/dodgybadger/assistantmd:v0.5.0) if you are not ready to migrate.**

AssistantMD turns a markdown vault into a collaborative workbench for you and an AI agent. It is built on three core principles:

- Full ownership of your files and workflows.
- Maximum flexibility to structure work around your needs.
- A markdown vault as the source of truth for you and the agent.

A vault is a collection of markdown files (borrowing the term from Obsidian). A personal vault might look like this:

```text
Personal_Vault/
├── Coursework/
│   └── HR Certificate/
│       ├── Module 01/
│       └── Module 02/
├── Projects/
│   ├── Grant Proposal/
│   └── Home Renovation/
└── Writing/
    ├── Research Briefs/
    └── Draft Essays/
```

Each folder can be both a place to organize your own knowledge and a shared workbench for collaborating with the agent. Keep notes, sources, drafts, prompts, skills, review items, and outputs together so the context you build for yourself is also the context the agent works from. For chat sessions, you can choose a workspace folder so the default context setup can load local orientation files such as `README.md` and `playbook.md`.

AssistantMD adds its own `AssistantMD/` folder for reusable skills, workflow scripts, exported chat transcripts, imports, and optional context files.

AssistantMD gives you a set of composable building blocks to shape agent behavior: chat for direct collaboration, skills for reusable procedures, workflows for repeatable or scheduled automation, context assembly for deciding what the agent sees, and session summaries for recalling prior work. Start with the default setup; it will get you pretty far. See the [Build Guide](docs/use/build-guide.md) for the full pattern.

### Chat

Use chat when you want the agent to work directly against your vault: answer questions from your notes, reorganize files, draft from existing material, or research something and save the result.

### Skills

Skills are markdown procedures. Use them when you want the agent to follow the same process every time: meeting prep, literature review, inbox triage, source evaluation, or report drafting.

### Workflow Scripts

Workflow scripts are Python stored in markdown files. Use them when work should run on a schedule or needs predictable sequencing: scan new notes, prepare a weekly review, summarize stale sessions, or maintain memory notes.

### Context Assembly

A context assembly script controls what the chat agent knows at the start of each session: history, files, skills, instructions, policies or memory notes.

### Long-term Context and Recall

AssistantMD does not impose one fixed memory model. The default setup uses two complementary patterns: user-owned markdown notes for explicit durable facts and preferences, and session summaries for recall across prior chats. Session summaries are searched through the `session_ops` tool; enable or customize the packaged nightly session summary workflow when you want them maintained automatically.

## Documentation

- **[Installation Guide](docs/setup/installation.md)**
- **[Build Guide](docs/use/build-guide.md)** — start here for the composable building blocks and default setup
- **[Authoring Reference](docs/use/authoring.md)** — workflow scripts and context assembly scripts
- **[Security Considerations](docs/setup/security.md)**
- **[Upgrading](docs/setup/upgrading.md)**


## Requirements

- Docker Engine or Docker Desktop
- At least one LLM API key or endpoint. AssistantMD can use OpenAI, Anthropic, Google, Mistral, Grok, OpenRouter, or OpenAI-compatible local/custom endpoints.
- Comfort with the terminal


## License

MIT — see [LICENSE](LICENSE).


## Attributions

Some design ideas in AssistantMD were shaped by the work of others:

- **RLM-style research loops**: https://alexzhang13.github.io/blog/2025/rlm/
- Third-party software notices: see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
