# AssistantMD

**AssistantMD aims to be the most productive AI harness for knowledge work.**

It brings AI chat, your Markdown knowledge base, and safe automation into one
self-hosted environment. Instead of copying results between chat, notes,
research tools, and scripts, you can let an agent work directly with the
material you care about and turn useful work into durable, inspectable
knowledge and repeatable processes.

When you begin a chat session, you can select any folder in your vault as its
workspace. The assistant uses that folder as the default project context, while
retaining access to the rest of the vault. Simple conventions such as
`README.md` and `playbook.md` help it quickly understand the project and follow
project-specific guidance.

Your Markdown files remain the durable source of truth: readable, portable, and
useful with or without AssistantMD. AssistantMD is the environment around them:
available wherever you host it, adaptable to the way you work, and designed to
give agents useful capabilities without handing them control of the host.

AssistantMD is shaped through daily use on real knowledge-work projects. Its
features grow from friction encountered there: copying useful material between
chat and notes, manually importing dozens of research sources, switching
applications just to make a small edit, or needing automation without giving an
agent unrestricted access to the host. Its development is guided by a simple
aim: keep removing the obstacles that interrupt productive work.

## Features

- Vaults are isolated from each other.
- Supports many API model providers as well as experimental OpenAI OAuth (ChatGPT / Codex subscription).
- Tuned for long-running tasks, tool-heavy agents, and deep work sessions.
- Browse, preview, edit, upload, move, and organize files in the Vault Explorer.
- Review and adjust agent file changes before approving them with Inline edit mode.
- Restore file revisions or roll back file changes from a completed activity.
- Attach images when using a multimodal chat model.
- Clean, minimal UI with focus and dark modes.
- Context overflow protection for large tool results.
- Nightly chat history summarization and indexing.
- Export chat sessions to markdown.
- Batch-import public URLs and vault PDFs to markdown in chat and workflows.
- Search, extract, and crawl web content with configurable retrieval strategies.
- Durable workflow history and searchable System Activity for operational visibility.
- Extensive settings for customizing runtime behavior.

And last but not least, **composability**. AssistantMD gives you a set of building blocks to shape
agent behavior as much as you want. The default composition will get you pretty far
by editing only markdown files. If that doesn't provide enough flexibility, you can create
your own Python workflow and context assembly scripts. Reusable and scheduled workflows live
in `AssistantMD/Authoring`, while project-specific workflows can live beside the content they
process and be run explicitly by the chat agent. See the [Build Guide](docs/use/build-guide.md)
for full details. Once AssistantMD is running, the chat agent can help you adapt the setup.

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

Likely future work includes UI element enhancement, improved provider caching, and carefully scoped
household/team deployment options that preserve AssistantMD's single-user vault model.

Exploratory areas include richer chat-session retrieval, prompt/eval tools, provider batch processing
for cheaper long-running workflows, and broader multimodal support.

## License

MIT — see [LICENSE](LICENSE).
