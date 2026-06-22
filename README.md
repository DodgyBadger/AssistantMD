# AssistantMD

AssistantMD turns a markdown vault into a collaborative workbench for you and an AI agent. It is built on three core principles:

- Full ownership of your files, skills, workflows and memory.
- Flexibility to structure work around your needs, even on a per-project basis.
- Plain text markdown files as the shared source of truth for you and the agent.

Your collection of markdown files is called a vault (borrowing the term from Obsidian). Each folder in your vault is both a place to organize your knowledge and projects, and a shared workspace for collaborating with the agent. At the start of each chat session, you can set a workspace folder so that the session stays oriented (but not locked) to that folder. Add `README.md` and `playbook.md` to your workspace folders to further orient and guide AI-assisted work sessions.

https://github.com/user-attachments/assets/5504eff3-3c5b-4a6d-9482-d1d15a8d76e1

## Features

- Mounted vaults are isolated from each other.
- Compatible with all major LLM providers and local models.
- Tuned for long-running tasks, tool-heavy agents, and deep work sessions.
- Image support.
- Clean, minimal UI including an even more minimal focus mode. And of course dark-mode!
- Context overflow protection for large tool results.
- Nightly chat history summarization and indexing.
- Export chat sessions to markdown.
- Import PDFs and URLs to markdown.
- Automatic tracking and snapshots of files changed through AssistantMD.
- Extensive settings for customizing runtime behavior.
- Smaller risk surface by focusing agent collaboration inside your vault instead of broad integrations.

And last but not least, **composability**. AssistantMD gives you a set of building blocks to shape agent behavior: chat for direct collaboration, skills for reusable procedures, workflows for repeatable or scheduled automation, context assembly for deciding what the agent sees, and session summaries for recalling prior work. Start with the default setup; it will get you pretty far. See the [Build Guide](docs/use/build-guide.md) for the full details; once AssistantMD is running, the chat agent can help you adapt the setup.

## Documentation

- **[Installation Guide](docs/setup/installation.md)**
- **[Build Guide](docs/use/build-guide.md)** — start here for the composable building blocks and default setup
- **[Authoring Reference](docs/use/authoring.md)** — workflow scripts and context assembly scripts
- **[Security Considerations](docs/setup/security.md)**
- **[Upgrading](docs/setup/upgrading.md)**


## Requirements

- Docker Engine or Docker Desktop
- At least one LLM API key or endpoint.
- Comfort with the terminal

## Roadmap

Likely future work includes OpenAI subscription support, better import workflows, direct vault-file browsing in the UI, improved provider caching, and carefully scoped household/team deployment options that preserve AssistantMD's single-user vault model.

Exploratory areas include richer chat-session retrieval, prompt/eval tools, provider batch processing for cheaper long-running workflows, and broader multimodal support.

## License

MIT — see [LICENSE](LICENSE).
