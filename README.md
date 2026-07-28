# AssistantMD

> 🚀 **New in v0.7:** Browse and edit your vault without leaving chat, review
> agent file changes inline, restore file revisions, and roll back completed
> activities. See the [release notes](RELEASE_NOTES.md) for details and upgrade
> guidance.

AssistantMD is a self-hosted AI chat interface and Markdown editor in one
focused work environment. Chat with an assistant, browse and edit
files, review proposed changes, and automate recurring work without moving
between separate applications.

Each area of your vault can support a different kind of work. Workspace
orientation, local playbooks, reusable skills, workflows, and configurable
context help adapt the assistant to the task without requiring you to build and
manage separate agents.

Your Markdown files remain the durable source of truth: readable, portable, and
useful with or without AssistantMD.

Any folder in a vault can be selected as the workspace for a chat session,
giving the assistant focused project context without restricting access to the
rest of the vault. Add a `README.md` or `playbook.md` to describe the project
and guide how the assistant works there.

https://github.com/user-attachments/assets/5504eff3-3c5b-4a6d-9482-d1d15a8d76e1

## Features

- Mounted vaults are isolated from each other.
- Supports many API model providers as well as experimental OpenAI OAuth (ChatGPT / Codex subscription).
- Tuned for long-running tasks, tool-heavy agents, and deep work sessions.
- Browse, preview, edit, upload, move, and organize vault files in the Vault Explorer.
- Review and adjust agent file changes before approving them with Inline edit mode.
- Restore file revisions or roll back all file changes from a completed activity.
- Attach images when using a multimodal chat model.
- Clean, minimal UI with focus and dark modes.
- Context overflow protection for large tool results.
- Nightly chat history summarization and indexing.
- Export chat sessions to markdown.
- Import PDFs and URLs to markdown.
- Search, extract, and crawl web content with configurable retrieval strategies.
- Durable workflow history and searchable System Activity for operational visibility.
- Extensive settings for customizing runtime behavior.
- Smaller risk surface by focusing agent collaboration inside your vault instead of broad integrations.

And last but not least, **composability**. AssistantMD gives you a set of building blocks to shape agent behavior: chat for direct collaboration, skills for reusable procedures, workflows for repeatable or scheduled automation, context assembly for deciding what the agent sees, and session summaries for recalling prior work. Start with the default setup; it will get you pretty far. See the [Build Guide](docs/use/build-guide.md) for the full details; once AssistantMD is running, the chat agent can help you adapt the setup.

## Documentation

- **[Installation Guide](docs/setup/installation.md)**
- **[Build Guide](docs/use/build-guide.md)** — start here for the composable building blocks and default setup
- **[Authoring Reference](docs/use/authoring.md)** — workflow scripts and context assembly scripts
- **[Security Considerations](docs/setup/security.md)**
- **[Upgrading](docs/setup/upgrading.md)**
- **[Release Notes](RELEASE_NOTES.md)**

## Requirements

- Docker Engine or Docker Desktop
- At least one LLM API key or endpoint
- Comfort with the terminal

## Roadmap

Likely future work includes better import workflows, improved provider caching, and carefully scoped household/team deployment options that preserve AssistantMD's single-user vault model.

Exploratory areas include richer chat-session retrieval, prompt/eval tools, provider batch processing for cheaper long-running workflows, and broader multimodal support.

## License

MIT — see [LICENSE](LICENSE).
