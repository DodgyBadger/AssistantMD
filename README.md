# AssistantMD

AssistantMD is a markdown-native agent harness for automating research and knowledge workflows. It works alongside Obsidian (or any markdown editor). Bring information into markdown, organize and automate with workflows and reason through it in a steerable chat UI where your data stays plain text and owned by you.

**What this is:** a focused workspace for markdown-first automation and knowledge work.  
**What this isn't:** a general purpose agent platform for managing your email or booking flights.

## Design philosophy

**Data ownership:** Wherever possible, AssistantMD uses markdown files so data remains accessible and can be version controlled. For functionality requiring a database, SQLite maintains the file-first approach. Even chat sessions are automatically saved as markdown in your vault.

**Explicit / minimal magic:** Plain-text control primitives let you compose a wide range of behaviours. Hidden defaults and magic behaviour are kept to a minimum. This makes templates a bit verbose, but also very flexible and traceable.

**Security:** The focus is safe, local automation on your markdown files. Prompt-injection is a core concern, so AssistantMD takes a cautious approach to untrusted web content and keeps external integrations intentionally narrow.

## Requirements

- Docker Engine or Docker Desktop
- At least one LLM API key
- Comfort with the terminal

## ✨ Features

Designed to work alongside Obsidian or other markdown editors.

**📥 Import Pipeline**
- Import PDFs and URLs into markdown and build a searchable project/research library in your vault.
- Keep source material in plain text for downstream workflows and chat.

**👷‍♂️ Scheduled Workflows**
- Multi-step, scheduled workflows. Each step can define prompt, model, tools and content routing.
- Define workflows using markdown templates in `AssistantMD/Workflows/`

**💬 Steerable Chat + Context Manager**
- Reason over your vault with controllable context, custom instructions, tools, and buffers.
- Define context templates in `AssistantMD/ContextTemplates`.

**🔐 Plain-Text Ownership & Control**
- Self-hosted, single-user design with markdown-first storage.
- Docker-based deployment, with data remaining local and inspectable.

**🤖 AI Providers**
- GPT, Claude, Gemini, Mistral, Grok
- Any OpenAI-compatible API (Ollama, etc.)

## Typical use cases

- Build a research library from PDFs and web pages, then work through it systematically in chat.
- Automate recurring knowledge workflows (planning, synthesis, note organization) on a schedule.
- Prototype prompt/workflow behavior before implementing full custom agents.

<img src="docs/chat-UI-screenshot.png" alt="Chat UI screenshot" height="700">

## 📚 Documentation

- **[Installation Guide](docs/setup/installation.md)**
- **[Basic Usage](docs/use/overview.md)**
- **[Context Manager](docs/use/context_manager.md)**
- **[Workflows](docs/use/workflows.md)**
- **[Security Considerations](docs/setup/security.md)**
- **[Upgrading](docs/setup/upgrading.md)**

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
