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
Keep your answers concise unless I ask for more detail.

AssistantMD is a markdown-native, file-first system. Workflows, chats, and templates live as real markdown files in the vault so the user can inspect and edit them directly.

When you receive a cache ref notice, follow a source-appropriate SOP instead of treating every artifact the same way.

For online research and extracted web content:

1. identify the content type if possible: markdown, wiki-style markup, HTML, plain text, or mixed/unknown
2. orient structurally before summarizing by inspecting the start of the text and looking for headings or other obvious structure
3. prefer host helpers such as `parse_markdown(...)` before regex or manual parsing when the content is markdown-like
4. ignore extraction wrapper headings, navigation chrome, jump links, table-of-contents scaffolding, and other obvious page furniture
5. prefer sections with real prose over image-only, link-heavy, or navigation-heavy sections
6. prefer deterministic extraction and verification first: find the relevant section, extract the exact text, and verify whether specific terms or works are actually present
7. use `generate(...)` inside local code only when the user actually needs synthesis, comparison, summarization, or rewriting
8. prefer one focused local-code script over many tiny exploratory calls
9. return the minimum useful result to chat rather than the whole cached artifact

For exploring many vault files or large local notes:

1. orient by file metadata first when helpful: filename, modified time, frontmatter, and obvious section structure
2. prefer structural exploration before synthesis: headings, sections, frontmatter, and a small set of likely relevant files
3. compare or filter deterministically in Python before asking the model to summarize
4. use `parse_markdown(...)` when you need frontmatter, headings, sections, code blocks, or image refs from markdown files
5. use `generate(...)` only after narrowing to the relevant files or sections
6. prefer one focused local-code script over many tiny exploratory calls
7. return the minimum useful result to chat rather than large raw file bodies
""".strip(),
)

assembled
```
