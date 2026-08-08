# AssistantMD

> 🚀 **New in v0.7:** Browse and edit your vault without leaving chat, review
> agent file changes inline, restore file revisions, and roll back completed
> activities. See the [release notes](RELEASE_NOTES.md) for details and upgrade
> guidance.

AssistantMD is a self-hosted AI chat interface and Markdown editor in one
focused work environment. Chat with an assistant, browse and edit
files, review proposed changes, and automate recurring work without moving
between separate applications.

Any folder in a vault can be selected as the workspace for a chat session,
giving the assistant focused project context . Add a `README.md` or `playbook.md`
to the workspace to describe the project and guide how the assistant works there.

Your Markdown files remain the durable source of truth: readable, portable, and
useful with or without AssistantMD.

## Features

- Vaults are isolated from each other.
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

And last but not least, **composability**. AssistantMD gives you a set of building blocks to shape agent behavior as much as you want. The default composition will get you pretty far
by editing only markdown files. If that doesn't provide enough flexibility, you can create
your own python workflow and context assembly scripts. See the [Build Guide](docs/use/build-guide.md) for full details. Once AssistantMD is running, the chat agent can help you adapt the setup.

## Documentation

- **[Installation Guide](docs/setup/installation.md)**
- **[Development Setup](docs/setup/development.md)**
- **[Build Guide](docs/use/build-guide.md)** — start here for the composable building blocks and default setup
- **[Authoring Reference](docs/use/authoring.md)** — workflow scripts and context assembly scripts
- **[Importing Content](docs/use/importing-content.md)** — import monitoring, queue controls, and timing configuration
- **[Security Considerations](docs/setup/security.md)**
- **[Upgrading](docs/setup/upgrading.md)**
- **[Release Notes](RELEASE_NOTES.md)**

## Requirements

- Docker Engine or Docker Desktop
- At least one LLM API key or OpenAI subscription
- Comfort with the terminal

## Roadmap

Likely future work includes better import workflows, improved provider caching, and carefully scoped household/team deployment options that preserve AssistantMD's single-user vault model.

Exploratory areas include richer chat-session retrieval, prompt/eval tools, provider batch processing for cheaper long-running workflows, and broader multimodal support.

## License

MIT — see [LICENSE](LICENSE).
