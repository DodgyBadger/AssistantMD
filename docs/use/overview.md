## How to use AssistantMD

When you first run the app, a new `AssistantMD` folder will be added to each of your vaults. This is where files live that are unique to how AssistantMD runs.
- `AssistantMD/Workflows` holds your workflow definitions
- `AssistantMD/Chat_Sessions` holds markdown files containing your chat history
- `AssistantMD/Import` is where you place files you want to import as markdown into your vault
- `AssistantMD/ContextTemplates` holds context manager templates

Once setup is complete, open the web app at `http://localhost:8000/` (or the host/port you configured).

### Chat

Chat works like other AI chats but with access to your markdown files. Open **Chat Settings**, pick a vault and model, then toggle tools as needed:

- **web_search** (default): duckduckgo (free) or tavily (API required, free tier available)
- **file_ops_safe** (default): search, read, create, append in your vault
- **file_ops_unsafe**: edit, move, delete
- **code_execution**: run code via Piston (public or self-hosted API)
- **workflow_run**: list workflows and run a workflow in the current vault
- **tavily_extract**: extract content from specific URLs (API required, free tier available)
- **tavily_crawl**: crawl and extract content from multiple pages (API required, free tier available)

**Security note**: The app has no built-in auth or TLS. Keep it on a trusted network or add your own [security layers](../setup/security.md).

### Context Manager

Context templates let you add custom system instructions and shape the context window seen by the chat agent. Templates live under `AssistantMD/ContextTemplates/` (vault-specific) or `system/ContextTemplates/` (global). Select a template per chat session in the UI.

Learn more in [Context Manager](context_manager.md).

### Workflows

Workflows allow you to schedule and structure prompts or sequences of prompts. Define a workflow by creating a markdown file inside `AssistantMD/Workflows/`.

[Go here](workflows.md) for more about creating workflows.

### Importer

Import PDFs and URLs into your vault as markdown. Drop files into `AssistantMD/Import/` for bulk imports, or point the importer at a URL to convert a page to markdown. Imports land under `Imported/` (configurable in the web UI).

**Note**: The importer is a work in progress and likely to change as I test different backend ingestion solutions.

### Configuration

Use the **Configuration** tab in the web UI to configure providers (e.g. OpenAI, Anthropic) and models and manage secrets (API keys). Models are aliases that map to provider model strings so you can update to the latest LLMs without editing every workflow and context template. Adjust general settings here too (timeouts, tool settings, etc.).

### Tips

- Use the built-in assistantmd_helper template to get information about this app. It has access to documentation and can answer questions about AssistantMD and build and test templates. Start simple, test and iterate.
- If using Obsidian, set up a base (Obsidian v1.9 or later) to view and manage all your workflow files and frontmatter properties in one place, making it easy to enable/disable or update schedules.
- If using Obsidian, enabled `Use [[Wikilinks]]` and set `New link format` to `Absolute path in vault` in `Settings > Files & Links`. This will allow you to drag-and-drop from the Obsidian file explorer into input and output directives. AssistantMD will ignore the square brackets (`[[filename]]`).

### Example Library

[See here](../examples/) for a growing library of example workflow and context templates. PRs accepted if you would like to submit your own for possible inclusion in the library. All submissions will be reviewed carefully to ensure no duplication or malicious instructions.
