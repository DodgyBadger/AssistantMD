# AssistantMD

AssistantMD is a markdown-native agent harness for automating research and knowledge workflows. It works alongside Obsidian (or any markdown editor). Bring information into markdown, organize and automate with workflows and reason through it in a steerable chat UI where your data stays plain text and owned by you.

## Typical use cases

**Deep research in the chat UI**  
Give AssistantMD a topic, focus and constraints, then let it run: search the web, open pages, pull key details and keep digging through follow-up searches. It can stash text in a buffer so the chat stays usable while it works through lots of material. You can keep asking follow-up questions as it goes, and have it write summary reports straight to your vault whenever you want.

**Project-aware chat**  
After building a research library, you can create a context template that loads the key project facts into each new chat. That way you can continue the work without re-explaining background details every time. It makes follow-on analysis, drafting and decision support much faster while staying grounded in your vault content.

**Scheduled workflows for planning and follow-through**
Set up workflows that run on a schedule and keep your notes up to date. For example, a weekly planner can scan your master task list, carry forward unfinished items from last week, integrate longer-term goals and draft a weekly plan. You can interact with the workflow agent through the notes. The result is a repeatable loop that is grounded in your markdown files and adapts as your notes change.

**Prototype prompts and workflows**  
AssistantMD can be used as a practical prototyping harness for building specialized agents. Draft or adjust a workflow, run it from chat with `workflow_run`, inspect the outputs in your vault and iterate on prompts, tools, models and step structure. The workflow engine architecture is extensible, so you can also mock up specialized engines beyond the built-in `step` engine when you need a different execution pattern.


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
- **[Architecture Overview](docs/architecture/overview.md)**
- **[Extending AssistantMD](docs/architecture/extending.md)**
- **[Validation Framework](docs/architecture/validation.md)**
- **[Security Considerations](docs/setup/security.md)**
- **[Upgrading](docs/setup/upgrading.md)**

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Attributions

Some design ideas in AssistantMD were shaped by the work of others:

- **RLM-style research loops**: [RLM: Rewriting the Language Model Loop](https://alexzhang13.github.io/blog/2025/rlm/)
- **Context engineering for long-running agents**: [Summary notes in this repo](context_management.md), covering themes from Google, Anthropic, Stanford/SambaNova ACE, and Manus.
