# AssistantMD

Markdown-native, self-hosted AI chat UI and scheduled workflows.

Runs in Docker alongside Obsidian, VSCode, or any markdown editor - mount your vault and you're done. No copying files, no plugin dependencies.

Run it locally or deploy to a VPS (you provide the security layer). Sync your files with tools like Obsidian's Remotely Save plugin for everywhere-access.

## Requirements

- Docker Engine or Docker Desktop
- At least one LLM API key

## ✨ Features

**🤖 AI Providers**
- OpenAI, Anthropic (Claude), Google (Gemini), Mistral
- Any OpenAI-compatible API (Ollama, etc.)

**💬 Chat Interface**
- Clean, focused chat UI
- Read and write markdown files during conversations
- Sessions auto-saved as markdown files
- Full vault context available to the AI

**⚡ Scheduled Workflows**
- Workflows defined as markdown files in `assistants/` folder
- Recurring schedules (cron) or one-time execution
- Multi-step workflows with per-step model and tool selection
- Dynamic file patterns: `{today}`, `{this-week}`, `{latest}`, etc.

**🔐 Privacy & Control**
- Self-hosted - your files stay on your infrastructure
- Docker-based deployment
- Single-user design (bring your own auth layer if needed)

## 🚀 Quick Start

```bash
mkdir -p assistantmd/system && cd assistantmd
wget https://raw.githubusercontent.com/DodgyBadger/AssistantMD/main/docker-compose.yml.example -O docker-compose.yml
# Edit docker-compose.yml: update vault path & timezone
docker compose up -d
```

Access at `http://localhost:8000` → Configure API keys → Start chatting

**[Full installation guide →](docs/setup/installation.md)**

## 📚 Documentation

- **[Installation Guide](docs/setup/installation.md)** - Complete setup instructions
- **[Creating Assistants](docs/setup/assistant-setup.md)** - Build your first workflow
- **[Directives Reference](docs/core/core-directives.md)** - Control workflow behavior
- **[Security Considerations](docs/security.md)** - Important security information

## 🗺️ Roadmap

- Import utility for non-markdown file types
- Better context management for web search workflows
- Image support
- UI improvements