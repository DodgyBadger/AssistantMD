# AssistantMD

**An experimental agent harness and chat UI for control freaks.**

- Scheduled workflows
- Context curation
- Controlled loading of large content
- Explicit tool enablement
- Markdown native

Runs in Docker alongside Obsidian, VSCode, or any markdown editor. Run it locally or deploy to a VPS (you provide the security layer).

⚠️ **Beta software** ⚠️

## Requirements

- Docker Engine or Docker Desktop
- At least one LLM API key
- Comfort with the terminal

## ✨ Features

**🥼 NEW: Context Manager**
- Steer your chat sessions by curating message history and passing custom system instructions
- Define templates using markdown in `AssistantMD/ContextTemplates`

**⚡ Scheduled Workflows**
- Multi-step, scheduled workflows. Each step can define prompt, model, tools and content routing.
- Define workslow using markdown in `AssistantMD/Workflows/`

**💬 Chat Interface**
- Full access to your markdown notes
- Chat sessions saved as markdown

**🤖 AI Providers**
- GPT, Claude, Gemini, Mistral, Grok
- Any OpenAI-compatible API (Ollama, etc.)

**🔐 Privacy & Control**
- Self-hosted, single-user design
- Docker-based deployment

<img src="docs/chat-UI-screenshot.png" alt="Chat UI screenshot" height="700">

## 📚 Documentation

- **[Installation Guide](docs/setup/installation.md)**
- **[Basic Usage](docs/use/overview.md)**
- **[Creating Workflows](docs/use/workflows.md)**
- **[Context Manager](docs/use/context_manager.md)**
- **[Security Considerations](docs/setup/security.md)**
- **[Upgrading](docs/setup/upgrading.md)**

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
