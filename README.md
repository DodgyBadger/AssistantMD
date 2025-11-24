# AssistantMD

Markdown-native, self-hosted AI chat UI and scheduled, multi-step prompts.

Runs in Docker alongside Obsidian, VSCode, or any markdown editor. Run it locally or deploy to a VPS (you provide the security layer).

**Examples use-cases:**
- 

⚠️ **Beta software. Back up your markdown files.**

## Requirements

- Docker Engine or Docker Desktop
- At least one LLM API key
- Comfort with the terminal 

## ✨ Features

**🤖 AI Providers**
- GPT, Claude, Gemini, Mistral, Grok
- Any OpenAI-compatible API (Ollama, etc.)

**💬 Chat Interface**
- Clean, mobile-friendly chat UI
- Read and write markdown files during conversations
- Full vault context available to the AI
- Easy to update models and providers

**⚡ Scheduled Workflows**
- Multi-step prompts (called workflows) with per-step model and tool selection
- Workflows defined as markdown files in `AssistantMD/Workflows/`
- Recurring schedules using cron expressions or one-time execution
- Dynamic file patterns: `{today}`, `{this-week}`, `{latest}`, etc.

**🔐 Privacy & Control**
- Self-hosted - your files stay on your infrastructure
- Docker-based deployment
- Single-user design (bring your own auth layer if needed)


## 📚 Documentation

- **[Installation Guide](docs/setup/installation.md)** - Complete setup instructions
- **[Creating Workflows](docs/setup/workflow-setup.md)** - Build your first workflow
- **[Directives Reference](docs/core/core-directives.md)** - Control workflow behavior
- **[Workflow Tips](docs/setup/tips.md)** - Additional tips for creating and managing workflows
- **[Security Considerations](docs/setup/security.md)** - Important security information
