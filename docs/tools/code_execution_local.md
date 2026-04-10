# `code_execution_local`

## Purpose

Run constrained local Python against the current chat session, cache scope, and optional vault file scope.

## When To Use

- you need small calculations or transformations
- you want to inspect cache artifacts by ref
- you want to explore vault files directly and `file_ops_safe` is enabled
- you need a small local loop around `retrieve`, `generate`, or `assemble_context`

## When Not To Use

- you need broader language support
- you need an external sandbox
- the task is simple enough to solve directly with another tool

## Arguments

- `code`: constrained Python snippet to execute
- `readable_cache_refs`: optional readable cache refs or glob patterns
- `writable_cache_refs`: optional writable cache refs or glob patterns
- `readable_file_paths`: optional explicit read scope when `file_ops_safe` is enabled
- `writable_file_paths`: optional explicit write scope when `file_ops_safe` is enabled

## Local Runtime Surface

The code runs inside the same constrained authoring runtime used by Monty workflows.

The most important helpers are:

- `retrieve(...)`
- `output(...)`
- `generate(...)`
- `call_tool(...)`
- `assemble_context(...)`
- `parse_markdown(...)`
- `finish(...)`

Use ordinary Python for filtering, sorting, selection, and control flow around those helpers.

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
- `pending: "include" | "only" = "include"`

`cache` options:

- none

`run` options:

- `limit: int | "all" = "all"`

Return shape:

- `result.type`
- `result.ref`
- `result.items`

Each retrieved item has:

- `item.ref`
- `item.content`
- `item.exists`
- `item.metadata`

Common file metadata fields:

- `filename`
- `filepath`
- `source_path`
- `extension`
- `size_bytes`
- `char_count`
- `token_estimate`
- `mtime_epoch`
- `ctime_epoch`
- `mtime`
- `ctime`
- `filename_dt`
- `error`

Examples:

```python
note = await retrieve(type="file", ref="notes/today.md")
```

```python
notes = await retrieve(type="file", ref="notes/*.md")
latest_three = sorted(
    [item for item in notes.items if item.exists],
    key=lambda item: item.metadata.get("mtime_epoch") or 0,
    reverse=True,
)[:3]
```

```python
history = await retrieve(type="run", ref="session", options={"limit": 3})
```

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

Return shape:

- `result.type`
- `result.ref`
- `result.status`
- `result.item.ref`
- `result.item.resolved_ref`
- `result.item.mode`

Examples:

```python
await output(type="file", ref="reports/daily.md", data=summary_text)
```

```python
await output(
    type="cache",
    ref="research/browser-page",
    data=page_text,
    options={"mode": "replace", "ttl": "24h"},
)
```

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

Arguments:

- `prompt`: required primary prompt
- `inputs`: optional retrieved source material
- `instructions`: optional extra system-style instruction
- `model`: optional model alias
- `tools`: optional explicit subset of allowed tools for this generation
- `cache`: optional generation memoization policy
- `options`: optional less-common controls such as `thinking`

Return shape:

- `result.status`
- `result.model`
- `result.output`

Notes:

- use `inputs=...` when you want host-managed source assembly
- plain text files can go through `inputs=...`
- direct images can go through `inputs=...`
- markdown files with embedded images can go through `inputs=...`
- tool use is opt-in; omit `tools` for plain generation

Examples:

```python
await generate(
    prompt="Summarize this note.",
    instructions="Be concise and factual.",
)
```

```python
image = await retrieve(type="file", ref="images/test_image.jpg")
await generate(
    prompt="Describe this image briefly.",
    inputs=image.items,
)
```

```python
note = await retrieve(type="file", ref="notes/trip-report.md")
await generate(
    prompt="Summarize this note and its embedded images.",
    inputs=note.items,
    instructions="Be concise.",
)
```

```python
await generate(
    prompt="Summarize and verify these leads.",
    instructions="Use search sparingly and cite concrete details.",
    tools=["web_search_tavily"],
)
```

### `call_tool`

```python
await call_tool(*, name: str, arguments: dict | None = None, options: dict | None = None)
```

Arguments:

- `name`: configured tool name
- `arguments`: optional keyword arguments for the tool
- `options`: reserved; keep empty or omit

Return shape:

- `result.name`
- `result.status`
- `result.output`
- `result.metadata`

Example:

```python
await call_tool(name="workflow_run", arguments={"operation": "list"})
```

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

Return shape:

- `result.messages`
- `result.instructions`

Each message has:

- `message.role`
- `message.content`
- `message.metadata`

Examples:

```python
history = await retrieve(type="run", ref="session", options={"limit": 3})
final = await assemble_context(history=history.items)
```

```python
history = await retrieve(type="run", ref="session", options={"limit": 3})
final = await assemble_context(
    history=history.items,
    instructions="Prefer exact quoted text when possible.",
)
```

### `parse_markdown`

```python
await parse_markdown(*, value: RetrievedItem | str)
```

Return shape:

- `parsed.frontmatter`
- `parsed.body`
- `parsed.headings`
- `parsed.sections`
- `parsed.code_blocks`
- `parsed.images`

Each heading has:

- `level`
- `text`
- `line_start`

Each section has:

- `heading`
- `level`
- `content`
- `line_start`

Each code block has:

- `language`
- `content`
- `line_start`

Each image has:

- `src`
- `alt`
- `title`
- `line_start`

Examples:

```python
doc = (await retrieve(type="file", ref="notes/reference.md")).items[0]
parsed = await parse_markdown(value=doc)
titles = [heading.text for heading in parsed.headings]
```

```python
skill = (await retrieve(type="file", ref="Skills/example.md")).items[0]
parsed = await parse_markdown(value=skill)
name = parsed.frontmatter.get("name")
description = parsed.frontmatter.get("description")
```

### `finish`

```python
await finish(*, status: str = "completed", reason: str | None = None)
```

Supported `status` values:

- `completed`
- `skipped`

Return shape:

- `result.status`
- `result.reason`

Example:

```python
await finish(status="skipped", reason="No inputs matched today.")
```

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

### Inspect a cache artifact

```python
code_execution_local(
    code="""
artifact = await retrieve(type="cache", ref="tool/example/ref")
artifact.items[0].content[:2000]
""",
    readable_cache_refs=["tool/example/ref"],
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

## Output Shape

Returns:

- the script return value when present
- printed output when present
- or a compact completion message

## Notes

- this tool always has access to the current chat session history
- cache and file access still depend on the granted scope
- prefer returning a compact final value instead of printing large text
- use this doc as the primary reference for the local helper surface
