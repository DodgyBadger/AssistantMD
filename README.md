# AssistantMD

AssistantMD turns a markdown vault into a collaborative workbench for you and an AI agent. It is built on three core principles:

- Full ownership of your files, skills, workflows and memory.
- Flexibility to structure work around your needs, even on a per-project basis.
- Plain text markdown files as the shared source of truth for you and the agent.

Your collection of markdown files is called a vault (borrowing the term from Obsidian). Each folder in your vault is both a place to organize your knowledge and projects, and a shared workspace for collaborating with the agent. At the start of each chat session, you can set a workspace folder so that the session stays oriented (but not locked) to that folder. Add `README.md` and `playbook.md` to your workspace folders to further orient and guide AI-assisted work sessions.

https://github.com/user-attachments/assets/887b05c8-ba99-4f47-9405-d5afcda7ce5c

## Features

- Mount one or more markdown vaults. Vaults are isolated from each other - each chat session is locked to exactly one vault.
- Compatible with all major LLM providers, including local models and any OpenAI-compatible endpoint. Supports API keys today; OpenAI subscription access via OAuth is in testing.
- Tuned for long-running tasks, tool-heavy agents, and deep work sessions.
- Image support for models that support it. Markdown files containing inline images are sent with interleaved text and images in the order they appear so the model has full contextual understanding.
- Clean, minimal UI including an even more minimal focus mode. And of course dark-mode!
- Agent tools: read/write to your vaults; web extraction, crawl and browser for online research; sandboxed code execution; chat history retrieval; subagents; run workflows; goal tracking for long-running tasks.
- Context overflow protection for large tool results.
- Nightly chat history summarization and indexing (disabled by default, enable in Dashboard > Workflows).
- Export chat sessions to markdown.
- Import PDFs and URLs to markdown using basic extraction, OCR (with Mistral API key), or converting PDF pages to images for when even OCR can't maintain sufficient fidelity.
- Automatic tracking and snapshots for vault files changed through AssistantMD.
- Model aliases so you don't have to update scripts every time you upgrade a model string.
- Extensive settings for model routing, tools, workflows, imports, memory, and runtime behavior.
- Smaller risk surface by focusing agent collaboration inside your vault instead of broad access to external apps, APIs, and integrations.

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
