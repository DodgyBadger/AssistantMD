## How to use AssistantMD

When you first run the app, a new `AssistantMD` folder will be added to each of your vaults. This is where files live that are unique to how AssistantMD runs.
- `AssistantMD/Workflows` holds your workflow definitions
- `AssistantMD/Chat_Sessions` holds markdown files containing your chat history
- `AssistantMD/Import` is where you place files you want to import as markdown into your vault

Once setup is complete, open the web app at `http://localhost:8000/` (or the host/port you configured).

### Chat

Chat works like other AI chats but with access to your markdown files. Open **Chat Settings**, pick a vault and model, then toggle tools as needed:

- **web_search** (default): duckduckgo (free) or tavily (paid/free tier)
- **file_ops_safe** (default, required): search, read, create, append in your vault
- **file_ops_unsafe**: full edit, move, delete
- **documentation_access**: lets the assistant reference these docs (great in workflow creation mode)
- **code_execution**: run code via Piston (public or self-hosted)
- **import_url**: convert a webpage to markdown and save it in your vault

**Security note**: The app has no built-in auth or TLS. Keep it on a trusted network or add your own security layers.

### Workflows

Workflows allow you to schedule and structure prompts or sequences of prompts. You define a workflow by creating a markdown file inside `AssistantMD/Workflows/`. Some workflow examples include:

- Every morning, review yesterday's meeting notes and extract action items to a to-do list
- Every month, search online and make a list of local events
- Daily, fetch data and run analysis using code_execution
- On a specific date, check a website for updates

[Go here](workflows.md) for more about creating workflows.

### Importer

Import PDFs and URLs into your vault as markdown. Drop files into `AssistantMD/Import/` for bulk imports, or point the importer at a URL to convert a page to markdown. Imports land under `Imported/` (configurable in the web UI). Word and other Office docs may be added in the future, but for now you can export them to PDF and import as above.

### Configuration

Use the **Configuration** tab in the web UI to configure providers (e.g. OpenAI, Anthropic) and models, and manage secrets (API keys). Models are aliases that map to provider model strings so you can update to the latest LLMs without editing every workflow. Adjust general settings here too (timeouts, tool settings, etc.).


### Tips for building workflows

🔶 Use the Chat UI in `Workflow Creation` mode to help you build workflows and refine the prompts.

🔶 Start with worflows disabled and test by running manually from the Workflow tab in the web UI. Enable and rescan when you are happy with the outputs.

🔶 Start simple, test and refine. One step with a compound prompt might do the trick. If not, split the prompt into two or more steps. Remember that each step can define a different `@model`, allowing for fine grained cost control.

🔶 Context is not passed automatically between steps. Use the `@output-file` of a previous step as `@input-file` in later steps to pass context. Nothing is assumed - you are always in control. You can have steps that build goals or checklists for later steps to process, allowing dynamic behaviour.

🔶 If using Obsidian, set up a base (Obsidian v1.9 or later) to view and manage all your workflow files and frontmatter properties in one place, making it easy to enable/disable or update schedules.

🔶 If using Obsidian, enabled `Use [[Wikilinks]]` and set `New link format` to `Absolute path in vault` in `Settings > Files & Links`. This will allow you to drag-and-drop from the Obsidian file explorer into input-file and output-file directives. AssistantMD will simply ignore the square brackets (`[[filename]]`).


