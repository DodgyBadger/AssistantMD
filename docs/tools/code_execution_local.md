# `code_execution_local`

## Purpose

Run constrained local Python against the current chat session and current AssistantMD runtime.

## Tool Argument

- `code`: constrained Python snippet to execute

## Local Runtime Surface

The code runs inside the same constrained authoring runtime used by Monty workflows.

Scope comes from the active chat session:

- file and history access come from the enabled tool surface
- tool access mirrors the enabled chat tools, excluding `code_execution_local` itself

Inside the runtime you have access to the following helper functions. Prefer these for the tasks described:

- `call_tool(...)`: invoke one already-enabled chat tool from inside the script.
- `pending_files(...)`: filter a file result set to the pending subset and explicitly complete the items you finished.
- `generate(...)`: run one explicit model call, optionally with file-backed inputs or bounded tool use.
- `assemble_context(...)`: build structured message history for downstream chat-style generation.
- `read_cache(...)`: open one cached oversized tool result by cache ref inside the current chat session.
- `parse_markdown(...)`: turn markdown into frontmatter, sections, headings, code blocks, and image refs.
- `finish(...)`: end the script intentionally with a completed or skipped terminal status.
- `date`: resolve common date tokens such as today, yesterday, week boundaries, and month names.

Use ordinary Python for everything else and for filtering, sorting, selection, and control flow around those helpers.

## Helper Signatures

### `read_cache`

```python
await read_cache(*, ref: str)
```

Notes:

- use this when chat tells you a large tool result was stored in a cache ref
- it reads cached content for the current chat session only
- the result is a `RetrievedItem`
- use attribute access, not dict access
- most scripts only need:
  - `artifact.exists: bool`
  - `artifact.content: str`
  - `artifact.metadata: dict`

### `pending_files`

```python
await pending_files(
    *,
    operation: str,
    pattern: str,
    items: CallToolResult | RetrievedItem | list[RetrievedItem] | tuple[RetrievedItem, ...],
)
```

Notes:

- use `operation="get"` to filter a `file_ops_safe` result down to pending items
- use `operation="complete"` to mark only the items you actually finished processing
- `pattern` is the stable tracking key, usually the watched glob such as `tasks/*.md`

### `generate`

```python
await generate(
    *,
    prompt: str,
    inputs: RetrievedItem | list[RetrievedItem] | tuple[RetrievedItem, ...] | None = None,
    instructions: str | None = None,
    model: str | None = None,
    tools: list[str] | tuple[str, ...] | None = None,
    cache: str | dict | None = None,
    options: dict | None = None,
)
```

Notes:

- tool use is opt-in; omit `tools` for plain generation
- prefer tool-first access patterns and keep `generate(...)` focused on the actual model call

### `call_tool`

```python
await call_tool(*, name: str, arguments: dict | None = None, options: dict | None = None)
```

Notes:

- this can only call tools already enabled for the chat run
- `code_execution_local` itself is excluded to avoid recursive self-invocation
- use this for file access, memory access, web tools, and other operational work
- prefer branching on `result.metadata` when the tool returns structured status

### `assemble_context`

```python
await assemble_context(
    *,
    history: list | tuple | None = None,
    context_messages: list | tuple | None = None,
    instructions: str | None = None,
    latest_user_message: object | None = None,
)
```

Notes:

- for conversation history, fetch explicit messages through `memory_ops` and pass them as `history`
- `latest_user_message` is only an explicit optional argument; it is not injected automatically by the runtime

### `parse_markdown`

```python
await parse_markdown(*, value: RetrievedItem | str)
```

Top-level fields:

- `parsed.frontmatter`
- `parsed.body`
- `parsed.headings`
- `parsed.sections`
- `parsed.code_blocks`
- `parsed.images`

Important:

- `parse_markdown(...)` returns objects with attributes, not dicts
- use `heading.text`, not `heading.get("text")`
- use `section.heading`, not `section["heading"]`

Common object shapes:

- `MarkdownHeading`
  - `text: str`
  - `level: int`
  - `slug: str | None`
  - `line: int | None`
- `MarkdownSection`
  - `heading: str`
  - `level: int`
  - `content: str`
  - `start_line: int | None`
  - `end_line: int | None`
- `MarkdownCodeBlock`
  - `lang: str | None`
  - `content: str`

Minimal example:

```python
parsed = await parse_markdown(value=markdown_text)

{
    "headings": [heading.text for heading in parsed.headings],
    "sections": [section.heading for section in parsed.sections],
    "code_langs": [block.lang for block in parsed.code_blocks],
}
```

### `finish`

```python
await finish(*, status: str = "completed", reason: str | None = None)
```

Supported `status` values:

- `completed`
- `skipped`

Important:

- `finish(...)` only supports keyword arguments
- return a value explicitly; do not rely on side effects alone
- the script result should be:
  - the last expression in the script, or
  - `await finish(status="...", reason="...")`

Examples:

```python
"ok"
```

```python
await finish(status="completed", reason="article summarized")
```

### `date`

```python
date.today(fmt: str | None = None) -> str
date.yesterday(fmt: str | None = None) -> str
date.tomorrow(fmt: str | None = None) -> str
date.this_week(fmt: str | None = None) -> str
date.last_week(fmt: str | None = None) -> str
date.next_week(fmt: str | None = None) -> str
date.this_month(fmt: str | None = None) -> str
date.last_month(fmt: str | None = None) -> str
date.day_name(fmt: str | None = None) -> str
date.month_name(fmt: str | None = None) -> str
```

Notes:

- these resolve the same shared date tokens used elsewhere in AssistantMD
- pass `fmt` to control formatting, using strftime, for example `date.today("%Y-%m-%d")`
- week-based values honor the current workflow or runtime `week_start_day`

## Common Patterns

### Simple calculation

```python
code_execution_local(
    code="""
total = sum([17, 23, 41])
str(total)
""",
)
```

### Use the built-in date helper

```python
code_execution_local(
    code="""
{
    "today": date.today("%Y-%m-%d"),
    "this_week": date.this_week("%Y-%m-%d"),
    "day_name": date.day_name(),
}
""",
)
```

### Read a tool doc

```python
code_execution_local(
    code="""
artifact = await call_tool(
    name="file_ops_safe",
    arguments={"operation": "read", "target": "__virtual_docs__/tools/code_execution_local"},
)
artifact.output[:2000]
""",
)
```

### Inspect a cached oversized tool result

```python
code_execution_local(
    code="""
artifact = await read_cache(ref="tool/tavily_extract/call_abc123")
artifact.content[:2000] if artifact.exists else "CACHE_NOT_FOUND"
""",
)
```

### Read cached extracted markdown and inspect headings

```python
code_execution_local(
    code="""
artifact = await read_cache(ref="tool/tavily_extract/call_abc123")
if not artifact.exists:
    await finish(status="skipped", reason="cache ref not found")

parsed = await parse_markdown(value=artifact.content)
[heading.text for heading in parsed.headings[:12]]
""",
)
```

### Explore a vault note structure

```python
code_execution_local(
    code="""
doc = await call_tool(
    name="file_ops_safe",
    arguments={"operation": "read", "target": "notes/project.md"},
)
parsed = await parse_markdown(value=doc.output)
[section.heading for section in parsed.sections]
""",
)
```

### Pull one section from extracted markdown

```python
code_execution_local(
    code="""
extracted = await call_tool(
    name="tavily_extract",
    arguments={"urls": ["https://example.com"]},
)
parsed = await parse_markdown(value=extracted.output)
target = next(
    (section for section in parsed.sections if section.heading == "AI In Fiction"),
    None,
)
target.content if target else "SECTION_NOT_FOUND"
""",
)
```

## Common Gotchas

- Do not import AssistantMD modules in these snippets. The runtime helpers are injected for you.
- Always return a value or `await finish(...)`. `finish(...)` is keyword-only.
- If a cached tool result already exists, use `await read_cache(ref="...")` instead of re-running the source tool.
- Prefer `parse_markdown(...)` over regex/manual parsing when the content is markdown or extracted article text.
- Some pages add wrapper headings such as extraction banners, navigation, or TOC chrome. Prefer the article's real prose sections over page furniture.

### Filter and complete pending files

```python
code_execution_local(
    code="""
listed = await call_tool(
    name="file_ops_safe",
    arguments={"operation": "list", "target": "tasks"},
)
pending = await pending_files(
    operation="get",
    pattern="tasks/*.md",
    items=listed,
)
selected = pending.items[:3]

# ...process selected...

await pending_files(
    operation="complete",
    pattern="tasks/*.md",
    items=selected,
)
""",
)
```

## Notes

- chat-session history is available through `memory_ops`
- cached oversized tool results are available through `read_cache(ref=...)`
- file, memory, and web access should generally go through `call_tool(...)`
- prefer returning a compact final value instead of printing large text
- use this doc as the primary reference for the local helper surface

## Common Monty Limits

- treat this as a constrained Monty runtime, not full CPython
- prefer host helpers such as `parse_markdown(...)` over regex/manual parsing when the content is markdown
- use one import per line
- prefer simpler Python and positional stdlib calls when possible
- if the script starts getting parser-heavy or utility-heavy, simplify the approach instead of layering more imports and boilerplate
