# AssistantMD

Self-hosted clean chat interface that can read and write to markdown files.  
Scheduled workflows that are defined by markdown files for quick setup and testing.  
Built with Obsidian in mind, but not tied to Obsidian.  
Run locally or on a cloud server (you must provide security - single user only).  

**Supports**
- OpenAI
- Anthropic
- Gemini
- Mistral
- any OpenAI compatible API (e.g. Ollama)

**Requires**
- Docker Engine / Docker Desktop
- At least one LLM API key

Read the [docs](docs/index.md) for full details.


## Use cases

**Your go-to chat interface.**  
Standard AI chat, but you can ask the AI save a summary / plan / recipe / whatever to markdown. Or ask the AI to read files as context for the chat. If you use Obsidian and have mounted your vault into AssistantMD, then files are instantly shared. No more copying and pasting. Chat sessions are automatically saved as markdown files, making them searchable in Obsidian.

How is this different from the many Obsidian AI plugins, or giving Claude Code or Codex access to your markdown files? The main difference is that AssistantMD runs in docker, making it highly portable. You can run it locally or you can set it up on a VPS (you must provide the security layer), sync your markdown files (e.g. using the excellent Remotely Save plugin in Obsidian) and then have everywhere-access to your files and chat.

There's also scheduled workflows (which you can use the chat to help you create) - read on.

**Workflows**  
After installing AssistantMD, a special "assistants" folder is created in each of your mounted vaults. To set up a workflow, you add a markdown file to this folder that specifies the run schedule and workflow steps. To edit a workflow, simply edit the markdown file and the changes will be picked up on the next run. Schedules can be recurring or once at a specific date-time. The full set of parameters allows for a lot of flexibility, from explicitly defined workflows to more agentic workflows.

I'm interested to hear what others can do with this app, and ideas for how to improve it. Currently on the roadmap:
- Import utility so you can get content from different file types into your vault
- Better context management (workflows using web search can get big if you're not careful)
- Image support
- UI improvements