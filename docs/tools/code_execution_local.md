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
- `parse_markdown(...)`: turn markdown into frontmatter, sections, headings, code blocks, and image refs.
- `finish(...)`: end the script intentionally with a completed or skipped terminal status.
- `date`: resolve common date tokens such as today, yesterday, week boundaries, and month names.

Use ordinary Python for everything else and for filtering, sorting, selection, and control flow around those helpers.

## Helper Signatures

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

### `finish`

```python
await finish(*, status: str = "completed", reason: str | None = None)
```

Supported `status` values:

- `completed`
- `skipped`

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

### Read conversation history with `memory_ops`

```python
code_execution_local(
    code="""
history = await call_tool(
    name="memory_ops",
    arguments={"operation": "get_history", "scope": "session", "limit": 5},
)
history.output
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

### Use multimodal inputs

```python
code_execution_local(
    code="""
result = await generate(
    prompt="Describe this topic briefly.",
    instructions="Return one short factual sentence.",
)
result.output
""",
)
```

### End-to-end markdown exploration

```python
code_execution_local(
    code="""
article = await call_tool(
    name="tavily_extract",
    arguments={"urls": ["https://example.com"]},
)
parsed = await parse_markdown(value=article.output)
history = await call_tool(
    name="memory_ops",
    arguments={"operation": "get_history", "scope": "session", "limit": 2},
)
assembled = await assemble_context(
    context_messages=[{"role": "system", "content": history.output}],
    instructions="Keep the summary concise.",
)
listing = await call_tool(
    name="file_ops_safe",
    arguments={"operation": "list", "target": "notes"},
)
draft = await generate(
    prompt=(
        f"title={parsed.frontmatter.get('title')}; "
        f"headings={len(parsed.headings)}; "
        f"messages={len(assembled.messages)}; "
        f"listing={listing.output}"
    ),
    instructions="Return one short deterministic line.",
)
await finish(status="completed", reason="article summarized")
""",
)
```

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
- file, memory, and web access should generally go through `call_tool(...)`
- prefer returning a compact final value instead of printing large text
- use this doc as the primary reference for the local helper surface

## Common Monty Limits

- treat this as a constrained Monty runtime, not full CPython
- prefer host helpers such as `parse_markdown(...)` over regex/manual parsing when the content is markdown
- use one import per line
- prefer simpler Python and positional stdlib calls when possible
- if the script starts getting parser-heavy or utility-heavy, simplify the approach instead of layering more imports and boilerplate
