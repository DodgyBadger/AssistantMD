# AssistantMD

AssistantMD is a markdown-native chat UI and agent harness for automating research and knowledge workflows. It works alongside Obsidian (or any markdown editor) so that you retain full control of your data (even your chat sessions are saved as markdown). Compose exactly the behaviour you want using a flexible set of control primitives in templates that sit alongside your other markdown files.

## Typical use cases

**Deep research in the chat UI**  
Give AssistantMD a topic, focus and constraints, then let it run: search the web, open pages, pull key details and keep digging through follow-up searches. It can stash text in a buffer so the chat stays usable while it works through lots of material. Have it write summary reports straight to your vault whenever you want.

**Project-aware chat**  
After building a research library, you can create a context template that loads the key project facts into each new chat. That way you can continue the work without re-explaining background details every time. It makes follow-on analysis, drafting and decision support much faster while staying grounded in your vault content.

**Scheduled workflows for planning and follow-through**
Set up workflows that run on a schedule and keep your notes up to date. For example, a weekly planner can scan your master task list, carry forward unfinished items from last week, integrate longer-term goals and draft a weekly plan. The result is a repeatable loop that is grounded in your markdown files and adapts as your notes change.

**Prototype prompts and workflows**  
AssistantMD can be used to rapidly prototype prompts, workflows and context architecture for specialized agents. Draft or adjust a workflow, run it from chat with `workflow_run`, inspect the outputs in your vault and iterate. The architecture is extensible, so you can also mock up specialized workflow engines when you need a different pattern.


## Design philosophy

**Data ownership:** Wherever possible, AssistantMD uses markdown files so data remains accessible and can be version controlled. For functionality requiring a database, SQLite maintains the file-first approach. Even chat sessions are automatically saved as markdown in your vault.

**Explicit / minimal magic:** Plain-text control primitives let you compose a wide range of behaviours. Hidden defaults and magic behaviour are kept to a minimum. Templates are explicit, flexible and traceable.

**Security:** The focus is safe, local automation on your markdown files. Prompt-injection is a core concern, so AssistantMD takes a cautious approach to untrusted web content and external integrations.

## Requirements

- Docker Engine or Docker Desktop
- At least one LLM API key
- Comfort with the terminal

## ✨ Features

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

## Attributions

Some design ideas in AssistantMD were shaped by the work of others:

- **RLM-style research loops**: [RLM: Rewriting the Language Model Loop](https://alexzhang13.github.io/blog/2025/rlm/)
- **Context engineering for long-running agents**: [Summary notes in this repo](context_management.md), covering themes from Google, Anthropic, Stanford/SambaNova ACE, and Manus.
