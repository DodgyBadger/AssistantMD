# Tool Docs Index

This folder contains one markdown document per user-facing tool.

Filename convention:

- the filename matches the tool name exactly
- example: the `browser` tool is documented in `browser.md`

How to use these docs:

- start here if you need to discover what tools exist
- open the matching tool document when you already know the tool name
- use `file_ops_safe(operation="list", path="__virtual_docs__/tools")` to inspect the tool docs directory
- use `file_ops_safe(operation="search", path="__virtual_docs__/tools", search_term="tool-name-or-concept")` to find the right doc or section
- use `file_ops_safe(operation="read", path="__virtual_docs__/tools/<tool_name>")` to read the matching tool doc
- prefer targeted reads over loading many tool docs at once
- when a matching doc exists, read it before guessing arguments or retrying tools repeatedly

General guidance:

- use search tools when you do not know the URL yet
- prefer `tavily_extract` over `browser` when you already know the URL and only need page content
- use `browser` when extract fails, returns thin content, or the page is clearly JavaScript-heavy
- prefer `code_execution_local` for small Python tasks tied to the current chat session
- `code_execution_local.md` is also the main reference for constrained runtime helpers, direct Monty tool calls, `generate(...)`, and `parse_markdown(...)`
- use `file_ops_safe` for exploration and non-destructive file work
- use `file_ops_unsafe` only when a destructive edit is explicitly needed

Available tool docs:

- `browser`
- `code_execution_local`
- `file_ops_safe`
- `file_ops_unsafe`
- `tavily_crawl`
- `tavily_extract`
- `web_search_duckduckgo`
- `web_search_tavily`
- `workflow_run`
