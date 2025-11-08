# AssistantMD

Chat with your markdown files.
Run scheduled workflows to interact with your markdown files.
Built with Obsidian in mind, but not tied to Obsidian.
Intended for a single-user environment.
Run locally or on a cloud server (but you must provide security).
Tool access is always explicit.

**Supports**
- OpenAI
- Anthropic
- Gemini
- Mistral
- any OpenAI compatible API (e.g. Ollama)

**Requires**
- Docker
- At least one LLM API key

Read the wiki for full details.

You only need Docker and a `docker-compose.yml` that points at the published
image (`ghcr.io/.../assistantmd`). Clone this repository only if you plan to
customize the source or build an image with different defaults (UID/GID, etc.).


**Known issues**

- **Context management**: There is a configurable cap on how many token a single web search, extraction or crawl can return, but not on the overall context window. Exceeding an LLM's context window (or rate limits) will throw an error. GPT-5 seems to be the worst offender for going overboard with web searches. Improved context management is on the roadmap, but for now please test your workflows for API cost and token accumulation. Start with smaller, cheaper models.
- **Thinking parameter**: The @model (thinking) parameter does not operate uniformly across model providers. This is because each provider approaches thinking / reasoning slightly differently. See core/core-directives.md for more details.
- **Text encoding**: Exporting text from other programs to .txt and then renaming to .md as a way to get content into your vault can surface text encoding errors. Workaround is to copy/paste as text into a fresh .md file rather than exporting. Roadmap includes an import utility to improve the workflow.
