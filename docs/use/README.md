## How to use AssistantMD

If you have not set up the app yet, start with the [Installation Guide](../setup/installation.md).
For a practical build path (chat -> skills -> workflow scripts -> advanced context scripts), start with the [Build Guide](build-guide.md) before diving into detailed references.

When you first run the app, a new `AssistantMD` folder is added to each vault:
- `AssistantMD/Authoring` holds your workflow script and context assembly script definitions
- `AssistantMD/Skills` holds your skill files
- `AssistantMD/Chat_Sessions` holds markdown files containing your chat history
- `AssistantMD/Import` is where you place files you want to import as markdown into your vault

Open the web app at `http://localhost:8000/` (or your configured host/port).

**Security note**: The app has no built-in auth or TLS. Keep it on a trusted network or add your own [security layers](../setup/security.md).

### Chat

Chat works like other AI chats, but with access to your vault files and enabled tools. Open **Chat Settings**, pick a vault and model, then toggle the tools you need.
Tool availability in the UI reflects current app configuration (`system/settings.yaml`).

**A note about chat sessions**: The chat UI does not show a session list. Each session is saved as a markdown transcript in `AssistantMD/Chat_Sessions`, and the agent can read those files. To continue an older thread, ask the agent to load it (for example, "continue our conversation about quantum entanglement").

### Workflow Scripts and Context Assembly Scripts

Workflow scripts automate vault tasks on a schedule or on demand. A Context Assembly Script shapes what the chat agent knows at the start of a session. Both are markdown authoring files in `AssistantMD/Authoring/`, each with YAML frontmatter and one fenced Python block.
See [Authoring](authoring.md).

### Importer

Import PDFs, images, and URLs into your vault. Drop files into `AssistantMD/Import/` for bulk import, or use URL import in the UI.
Use PDF mode `Markdown` for normal text extraction and `Page Images` when layout fidelity matters.
Imports are written under `Imported/` (configurable) with one folder per import.

### Configuration

Use the **Configuration** tab to manage providers, model aliases, secrets, and general settings.

### Example Library

[See here](../examples/README.md) for example workflow scripts and skills you can copy and adapt.
