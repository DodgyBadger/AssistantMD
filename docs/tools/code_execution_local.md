# `code_execution_local`

## Purpose

Run constrained local Python against the current chat session, cache scope, and optional vault file scope.

## Tool Argument

- `code`: constrained Python snippet to execute

## Local Runtime Surface

The code runs inside the same constrained authoring runtime used by Monty workflows.

Scope comes from the active chat session:

- cache access is available for the current chat session
- file access is available when `file_ops_safe` is enabled for the chat run
- tool access mirrors the enabled chat tools, excluding `code_execution_local` itself

Inside the runtime you have access to the following helper functions. Prefer these for the tasks described:

- `retrieve(...)`: load scoped files, cache artifacts, or recent chat-session history into the script.
- `output(...)`: write selected results back to a file or cache artifact.
- `generate(...)`: run one explicit model call, optionally with file-backed inputs or bounded tool use.
- `call_tool(...)`: invoke one already-enabled chat tool from inside the script.
- `assemble_context(...)`: build structured message history for downstream chat-style generation.
- `parse_markdown(...)`: turn markdown into frontmatter, sections, headings, code blocks, and image refs.
- `finish(...)`: end the script intentionally with a completed or skipped terminal status.

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
- `pending: "include" | "only" = "include"`

`cache` options:

- none

`run` options:

- `limit: int | "all" = "all"`

Results come back in `result.items`. For most scripts, the important fields are
`item.content`, `item.exists`, and `item.metadata`.

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
    readable_cache_refs=["research/article"],
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
    readable_cache_refs=["research/article"],
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
    readable_cache_refs=["research/article"],
    writable_cache_refs=["scratch/article-summary"],
)
```

## Notes

- this tool always has access to the current chat session history
- cache and file access still depend on the granted scope
- prefer returning a compact final value instead of printing large text
- use this doc as the primary reference for the local helper surface

## Common Monty Limits

- treat this as a constrained Monty runtime, not full CPython
- prefer host helpers such as `parse_markdown(...)` over regex/manual parsing when the content is markdown
- use one import per line
- prefer simpler Python and positional stdlib calls when possible
- if the script starts getting parser-heavy or utility-heavy, simplify the approach instead of layering more imports and boilerplate
