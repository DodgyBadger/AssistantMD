# AssistantMD

Markdown-native, self-hosted AI chat UI and scheduled, multi-step prompts.

Runs in Docker alongside Obsidian, VSCode, or any markdown editor. Run it locally or deploy to a VPS (you provide the security layer).

**Examples use-cases:**
- Instant read/write to your markdown files in the chat UI. No copying and pasting content.
- Run a prompt at 6am every day to review the latest meeting notes and summarize actions.
- Run a prompt monthly to find local events you might like and write them to a note.
- Run a multi-step workflow (sequence of prompts) to conduct online research for latest trends in your industry, create a weekly briefing note and recommended actions.

⚠️ **Beta software. Back up your markdown files before installing.**

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

- **[Installation Guide](docs/setup/installation.md)**
- **[Basic Usage](docs/use/overview.md)**
- **[Creating Workflows](docs/use/workflows.md)**
- **[Security Considerations](docs/setup/security.md)**
- **[Upgrading](docs/setup/upgrading.md)**

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
