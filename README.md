# AssistantMD

Markdown-native, self-hosted AI chat UI and scheduled workflows.

Runs in Docker alongside Obsidian, VSCode, or any markdown editor - mount your vault and you're done. No copying files, no plugin dependencies.

Run it locally or deploy to a VPS (you provide the security layer). Sync your files with tools like Obsidian's Remotely Save plugin for everywhere-access.

## Requirements

- Docker Engine or Docker Desktop
- At least one LLM API key

## ✨ Features

**🤖 AI Providers**
- GPT, Claude, Gemini, Mistral, Grok
- Any OpenAI-compatible API (Ollama, etc.)

**💬 Chat Interface**
- Clean, mobile-friendly focused chat UI
- Read and write markdown files during conversations
- Full vault context available to the AI
- Easy to update models and providers

**⚡ Scheduled Workflows**
- Workflows defined as markdown files in `AssistantMD/Workflows/`
- Recurring schedules (cron) or one-time execution
- Multi-step workflows with per-step model and tool selection
- Dynamic file patterns: `{today}`, `{this-week}`, `{latest}`, etc.

**🔐 Privacy & Control**
- Self-hosted - your files stay on your infrastructure
- Docker-based deployment
- Single-user design (bring your own auth layer if needed)

## 🚀 Quick Start

```bash
mkdir -p AssistantMD/system && cd AssistantMD
wget https://raw.githubusercontent.com/DodgyBadger/AssistantMD/main/docker-compose.yml.example -O docker-compose.yml
# Edit docker-compose.yml: update vault path & timezone
docker compose up -d
```

Access at `http://localhost:8000` → Configure API keys → Start chatting


## 📚 Documentation

- **[Installation Guide](docs/setup/installation.md)** - Complete setup instructions
- **[Creating Workflows](docs/setup/workflow-setup.md)** - Build your first workflow
- **[Directives Reference](docs/core/core-directives.md)** - Control workflow behavior
- **[Workflow Tips](docs/setup/tips.md)** - Additional tips for creating and managing workflows
- **[Security Considerations](docs/setup/security.md)** - Important security information
