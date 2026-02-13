## How to use AssistantMD

When you first run the app, a new `AssistantMD` folder will be added to each of your vaults. This is where files live that are unique to how AssistantMD runs.
- `AssistantMD/Workflows` holds your workflow definitions
- `AssistantMD/Chat_Sessions` holds markdown files containing your chat history
- `AssistantMD/Import` is where you place files you want to import as markdown into your vault
- `AssistantMD/ContextTemplates` holds context manager templates

Once setup is complete, open the web app at `http://localhost:8000/` (or the host/port you configured).

### Chat

Chat works like other AI chats but with access to your markdown files. Open **Chat Settings**, pick a vault and model, then toggle tools as needed:

- **web_search** (default): duckduckgo (free) or tavily (paid/free tier)
- **file_ops_safe** (default, required): search, read, create, append in your vault
- **file_ops_unsafe**: full edit, move, delete
- **code_execution**: run code via Piston (public or self-hosted)
- **workflow_run**: list workflows and run a workflow in the current vault
- **tavily_extract**: extract content from specific URLs
- **tavily_crawl**: crawl and extract content from multiple pages

**Security note**: The app has no built-in auth or TLS. Keep it on a trusted network or add your own security layers.

### Context Manager

**⚠️ This is an experimental feature and may change significantly in the future!!**

Context templates let you add custom system instructions to chat sessions and optionally enable history curation. Templates live under `AssistantMD/ContextTemplates/` (vault-specific) or `system/ContextTemplates/` (global). You select a template per chat session in the UI.

Learn more in [Context Manager](context_manager.md).

### Workflows

Workflows allow you to schedule and structure prompts or sequences of prompts. You define a workflow by creating a markdown file inside `AssistantMD/Workflows/`. Some workflow examples include:

- Every morning, review yesterday's meeting notes and extract action items to a to-do list
- Every month, search online and make a list of local events
- Daily, fetch data and run analysis using code_execution
- On a specific date, check a website for updates

[Go here](workflows.md) for more about creating workflows.

### Importer

Import PDFs and URLs into your vault as markdown. Drop files into `AssistantMD/Import/` for bulk imports, or point the importer at a URL to convert a page to markdown. Imports land under `Imported/` (configurable in the web UI).

**Note**: The importer is a work in progress and likely to change as I test different solutions.

### Configuration

Use the **Configuration** tab in the web UI to configure providers (e.g. OpenAI, Anthropic) and models, and manage secrets (API keys). Models are aliases that map to provider model strings so you can update to the latest LLMs without editing every workflow. Adjust general settings here too (timeouts, tool settings, etc.).


### Best practices

See [Best Practices](best_practices.md) for workflow and chat tips.
