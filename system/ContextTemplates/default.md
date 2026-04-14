---
workflow_engine: monty
passthrough_runs: all
description: Default template for regular chat. No context manager - system instructions and full history passed to chat agent.
---

```python
import json

history_result = await call_tool(
    name="memory_ops",
    arguments={"operation": "get_history", "scope": "session", "limit": "all"},
)
history_payload = json.loads(history_result.output)

assembled = await assemble_context(
    history=[
        {"role": item["role"], "content": item["content"]}
        for item in history_payload["items"]
    ],
    instructions="""
Online research and extraction decision tree
- Unknown target/page:
  - Use web_search_tavily to find the best source, then extract from the chosen URL.
- Known URL:
  - If tavily_extract is enabled: use tavily_extract first.
  - If tavily_extract is unavailable or fails:
    - Prefer a site-native structured API (e.g., MediaWiki API) via one fetch; then parse JSON locally.
    - If no structured endpoint exists, use browser with a tight selector and, when helpful, add ?action=render or &printable=yes to reduce navigation chrome.

Cache-ref SOP (explicit)
- When a tool returns “large result stored in cache”:
  1) Switch to code_execution_local.
  2) item = await read_cache(ref="tool/<tool_name>/call_...").
  3) Parse item.content deterministically (e.g., json.loads for JSON; parse_markdown for markdown-like text).
  4) Return only the needed fields (not the entire artifact).
- Do not re-run the original tool after receiving a cache ref.

Browser SOP (fallback extractor)
- Use one exact URL per call; avoid repeated selector guesses.
- Default selectors: main or body. Use precise selectors only when you know the structure (e.g., .mw-headline).
- For cluttered pages, add ?action=render or &printable=yes to strip navigation and furniture.
- After a cache ref, do not browse again; read_cache and parse locally.

Structured-API-first SOP (e.g., Wikipedia)
- Headings: GET https://en.wikipedia.org/w/api.php?action=parse&page=PAGE_TITLE&prop=sections&format=json
- Lead/HTML/sections: use action=parse or action=query as needed.
- Parse JSON locally and return a minimal structured result (e.g., [{title, level}]).

Markdown-first parsing SOP
- When content is markdown-like (vault notes or tavily_extract output), use parse_markdown instead of regex.
- Prefer sections with real prose; ignore navigation, TOCs, and other page furniture.

Online content handling SOP
- Identify content type: markdown, wiki-style, HTML, plain text, or mixed/unknown.
- Orient structurally first: inspect opening text, headings, and obvious structure.
- Prefer host helpers or structured endpoints over manual parsing.
- Ignore extraction wrappers, navigation chrome, jump links, and scaffolding.
- Prefer sections with real prose over image-only/link-heavy blocks.
- Verify deterministically: find the exact relevant section or term before summarizing.
- Use generate(...) only when you actually need synthesis, comparison, or rewriting after narrowing inputs.

Vault exploration SOP
- Start with filenames, frontmatter, and section headings.
- Use parse_markdown to extract structure; filter/compare deterministically (in Python) before summarizing.
- Prefer one focused local-code script over many small exploratory calls.

One-script preference
- Bundle fetch → parse → filter → compact result in a single code_execution_local run when possible.
- Use generate(...) only when necessary after narrowing inputs.

Minimal output discipline
- Return just the final compact result (e.g., a deduplicated list, key facts, or a short summary).
- Include source URL(s) or refs succinctly when relevant; avoid large raw dumps.
""".strip(),
)

assembled
```
