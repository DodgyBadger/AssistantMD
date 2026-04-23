# AssistantMD

AssistantMD is a **markdown-native chat UI** and **agent harness** for automating research and knowledge workflow scripts. It works alongside Obsidian (or any markdown editor) so you retain **full control of your data**: chats, skills, workflow scripts, and automation outputs are saved as plain markdown that you can inspect and version control.

> **Security note:** AssistantMD has **no built-in auth or TLS**. Run it on a trusted network and/or add your own security layers. See [docs/setup/security.md](docs/setup/security.md).


## Why AssistantMD

- **File-first ownership:** Markdown wherever possible; SQLite only when a database is required.
- **Vault-native automation:** Skills, workflow scripts, and agent behaviour are defined in plain markdown files that live inside your vault alongside your notes.
- **Cautious automation:** Built with prompt-injection awareness and a conservative stance toward untrusted content.


## How it works

When you run AssistantMD, it adds an `AssistantMD/` folder to each mounted vault:

- `AssistantMD/Skills/` — skill files that teach the agent reusable procedures
- `AssistantMD/Authoring/` — workflow scripts and context assembly scripts
- `AssistantMD/Chat_Sessions/` — exported chat transcripts
- `AssistantMD/Import/` — drop PDFs and images here to import to markdown

### Skills

A skill is a plain markdown file describing a task procedure. The default context assembly script loads your skills catalog at the start of each chat session so the agent can reference them as needed. Or integrate the skills library into your own workflow scripts and context scripts however you want. Write skills in plain English — no special syntax required.

### Workflow Scripts

Workflow scripts are Python scripts stored in markdown files in your vault. Use them for scheduled automations or tasks that need strict sequencing, conditional logic, or deterministic file routing. You don't write the Python yourself — describe what you want to the chat agent and it drafts the file for you.

### Context Assembly Script

A Context Assembly Script controls what the chat agent knows at the start of each session: which history it sees, what files are loaded, and what instructions it operates under. AssistantMD ships with a global default script that loads skills, passes full message history, and allows simple persona customization in `AssistantMD/soul.md`.

### Memory

AssistantMD doesn't take an opinionated approach to memory. Rather than imposing a fixed memory model, it gives you the building blocks to construct whatever fits your needs: context scripts that load relevant history or summaries, workflow scripts that distill and persist information across sessions, and plain markdown files that act as long-term memory stores the agent can read and write directly. More dedicated memory tooling is on the roadmap.

## Typical use cases

**Deep research** — Give AssistantMD a research goal and let it run: search, open pages, extract details, and synthesize findings into a report in your vault.

**Project-aware chat** — Skills and context assembly scripts give the agent knowledge of your vault structure, active projects, and preferred working style so you can jump into new chats without re-establishing context.

**Scheduled automation** — Run workflow scripts on a schedule to keep notes and plans current (scan new notes, extract actions, update a task list, generate weekly summaries).

## Documentation

- **[Installation Guide](docs/setup/installation.md)**
- **[Build Guide](docs/use/build-guide.md)** — start here for a practical walkthrough
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
