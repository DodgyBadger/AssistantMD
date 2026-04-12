# `code_execution_local`

## Purpose

Run constrained local Python against the current chat session and current AssistantMD runtime.

## Tool Argument

- `code`: constrained Python snippet to execute

## Local Runtime Surface

The code runs inside the same constrained authoring runtime used by Monty workflows.

Scope comes from the active chat session:

- cache access is available for the current chat session
- file access is available through the current AssistantMD runtime
- tool access mirrors the enabled chat tools, excluding `code_execution_local` itself

Inside the runtime you have access to the following helper functions. Prefer these for the tasks described:

- `retrieve(...)`: load scoped files, cache artifacts, or recent chat-session history into the script.
- `complete_pending(...)`: mark selected pending file items as processed after successful handling.
- `output(...)`: write selected results back to a file or cache artifact.
- `generate(...)`: run one explicit model call, optionally with file-backed inputs or bounded tool use.
- `call_tool(...)`: invoke one already-enabled chat tool from inside the script.
- `assemble_context(...)`: build structured message history for downstream chat-style generation.
- `parse_markdown(...)`: turn markdown into frontmatter, sections, headings, code blocks, and image refs.
- `finish(...)`: end the script intentionally with a completed or skipped terminal status.
- `date`: resolve common date tokens such as today, yesterday, week boundaries, and month names.

Use ordinary Python for everything else and for filtering, sorting, selection, and control flow around those helpers.

## Helper Signatures

### `retrieve`

```python
await retrieve(*, type: str, ref: str, options: dict | None = None)
```

Supported `type` values:

- `file`
- `cache`
- `run`

`file` options:

- `refs_only: bool = False`
- `pending: bool = False`

`cache` options:

- none

`run` options:

- `limit: int | "all" = "all"`

Results come back in `result.items`. For most scripts, the important fields are
`item.content`, `item.exists`, and `item.metadata`.

For simple boolean flags, `options` may also be written as a set of flag names,
for example `options={"pending"}`.

### `output`

```python
await output(*, type: str, ref: str, data: object, options: dict | None = None)
```

Supported `type` values:

- `file`
- `cache`

`file` options:

- `mode: "append" | "replace" | "new" = "append"`

`cache` options:

- `mode: "append" | "replace" = "append"`
- `ttl: str = "session"`

### `complete_pending`

```python
await complete_pending(
    *,
    items: RetrieveResult | RetrievedItem | list[RetrievedItem] | tuple[RetrievedItem, ...],
)
```

Notes:

- use this only with items returned from `retrieve(type="file", ..., options={"pending"})`
- acknowledge only the items you actually finished processing
- this is what prevents those files from being returned as pending on the next run

### `generate`

```python
await generate(
    *,
    prompt: str,
    inputs: RetrieveResult | RetrievedItem | list[RetrievedItem] | tuple[RetrievedItem, ...] | None = None,
    instructions: str | None = None,
    model: str | None = None,
    tools: list[str] | tuple[str, ...] | None = None,
    cache: str | dict | None = None,
    options: dict | None = None,
)
```

Notes:

- use `inputs=...` when you want host-managed source assembly
- plain text files can go through `inputs=...`
- direct images can go through `inputs=...`
- markdown files with embedded images can go through `inputs=...`
- tool use is opt-in; omit `tools` for plain generation

### `call_tool`

```python
await call_tool(*, name: str, arguments: dict | None = None, options: dict | None = None)
```

Notes:

- this can only call tools already enabled for the chat run
- `code_execution_local` itself is excluded to avoid recursive self-invocation

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

### Inspect a cache artifact

```python
code_execution_local(
    code="""
artifact = await retrieve(type="cache", ref="tool/example/ref")
artifact.items[0].content[:2000]
""",
)
```

### Explore extracted markdown before reaching for regex

```python
code_execution_local(
    code="""
artifact = await retrieve(type="cache", ref="research/article")
parsed = await parse_markdown(value=artifact.items[0].content)
{
    "title": parsed.frontmatter.get("title"),
    "headings": [heading.text for heading in parsed.headings],
}
""",
)
```

### Explore markdown structure

```python
code_execution_local(
    code="""
doc = await retrieve(type="file", ref="notes/project.md")
parsed = await parse_markdown(value=doc.items[0])
[section.heading for section in parsed.sections]
""",
)
```

### Enumerate pending files

```python
code_execution_local(
    code="""
pending = await retrieve(
    type="file",
    ref="tasks/*.md",
    options={"pending": True, "refs_only": True},
)
[item.ref for item in pending.items if item.exists]
""",
)
```

### Complete a processed pending batch

```python
code_execution_local(
    code="""
pending = await retrieve(type="file", ref="tasks/*.md", options={"pending"})
selected = tuple(pending.items[:3])
# ...process selected...
await complete_pending(items=selected)
""",
)
```

### Pull one section from extracted markdown

```python
code_execution_local(
    code="""
artifact = await retrieve(type="cache", ref="research/article")
parsed = await parse_markdown(value=artifact.items[0].content)
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
image = await retrieve(type="file", ref="images/test_image.jpg")
result = await generate(
    prompt="Describe this image briefly.",
    inputs=image.items,
)
result.output
""",
)
```

### End-to-end markdown exploration

```python
code_execution_local(
    code="""
article = await retrieve(type="cache", ref="research/article")
parsed = await parse_markdown(value=article.items[0].content)
history = await retrieve(type="run", ref="session", options={"limit": 2})
assembled = await assemble_context(
    history=history.items,
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
await output(
    type="cache",
    ref="scratch/article-summary",
    data=draft.output,
    options={"mode": "replace", "ttl": "session"},
)
await finish(status="completed", reason="article summarized")
""",
)
```

## Notes

- this tool always has access to the current chat session history
- cache and file access come from the current AssistantMD runtime
- prefer returning a compact final value instead of printing large text
- use this doc as the primary reference for the local helper surface

## Common Monty Limits

- treat this as a constrained Monty runtime, not full CPython
- prefer host helpers such as `parse_markdown(...)` over regex/manual parsing when the content is markdown
- use one import per line
- prefer simpler Python and positional stdlib calls when possible
- if the script starts getting parser-heavy or utility-heavy, simplify the approach instead of layering more imports and boilerplate
