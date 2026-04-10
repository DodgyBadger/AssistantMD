# Constrained Python Runtime Contract

This document describes the current constrained-Python runtime contract in AssistantMD.
Use it together with the inspectable authoring contract exposed by the authoring API.

## Overview

AssistantMD exposes a constrained Python sandbox for authored automation and chat-side local code execution.

AssistantMD exposes a focused runtime for explicit orchestration with a small host API, typed results, and host-enforced capability boundaries.

The current built-in runtime capabilities are:

- `retrieve(...)` to read scoped external inputs into the runtime
- `generate(...)` to perform one explicit model call, optionally with an explicit tool subset
- `output(...)` to write selected results out
- `call_tool(...)` to invoke one declared host tool explicitly
- `assemble_context(...)` to build validated downstream chat context from structured history and instructions

Capability results are returned as Python objects with attribute access, for example:

```python
source = await retrieve(type="file", ref="notes/today.md")
note_content = source.items[0].content

draft = await generate(
    prompt=f"Summarize this note:\n\n{note_content}",
    instructions="Be concise.",
)

await output(type="file", ref="reports/daily.md", data=draft.output)
```

## Runtime Environment

The runtime is intentionally small and explicit.

Current built-ins and conventions:

- `retrieve(type=..., ref=..., options=...)`
- `generate(prompt=..., inputs=..., instructions=..., model=..., tools=..., cache=..., options=...)`
- `output(type=..., ref=..., data=..., options=...)`
- `call_tool(name=..., arguments=..., options=...)`
- `assemble_context(history=..., context_messages=..., instructions=..., latest_user_message=...)`

Capability return values use attribute access:

- `source.items[0].content`
- `draft.output`
- `written.item.resolved_ref`
- `tool_result.output`

Supported resource types currently include:

- `file`
- `cache`
- `run`

Current retrieval and output surfaces are intentionally typed:

- `retrieve(type="file", ...)`
- `retrieve(type="cache", ...)`
- `retrieve(type="run", ref="session", ...)`
- `output(type="file", ...)`
- `output(type="cache", ...)`

`generate(..., cache=...)` provides host-managed memoization for the model call
itself. Use `output(type="cache", ...)` when you want a named retrievable cache
artifact.

A host-provided `date` object is available for runtime-oriented date helpers such as:

- `date.today()`
- `date.tomorrow()`
- `date.yesterday()`
- `date.this_week()`
- `date.last_week()`
- `date.next_week()`
- `date.this_month()`
- `date.last_month()`
- `date.day_name()`
- `date.month_name()`

Each date method also supports an optional format string such as `date.today("YYYYMMDD")`.

You can use the frontmatter option `week_start_day: ...` with week-based helpers such as
`date.this_week()`, `date.last_week()`, and `date.next_week()`. When omitted, the default
is `monday`.

The security boundary is enforced by the host:

- `retrieve(type="file", ...)` is denied unless file scope allows the target ref
- `retrieve(type="cache", ...)` is denied unless cache scope allows the target ref
- `retrieve(type="run", ...)` requires host-provided chat session history
- `output(type="file", ...)` is denied unless file scope allows the target ref
- `output(type="cache", ...)` is denied unless cache scope allows the target ref
- `call_tool(...)` is denied unless tool scope allows the named tool
- `generate(..., tools=[...])` may only use tools allowed by `authoring.tools`

## Rules

- Prefer explicit orchestration in Python over hidden framework behavior.
- Use built-in capabilities such as `retrieve(...)`, `generate(...)`, and `output(...)` for host boundary crossings.
- Use `assemble_context(...)` to build validated downstream chat context from structured history and instructions.
- Treat the host scope as a real security boundary.
- Treat `type`, `ref`, and `options` as the stable contract shape for resource-oriented capabilities.
- Build prompts explicitly in Python so retrieved content can be placed exactly where it belongs.
- Use `generate(..., inputs=...)` when retrieved file artifacts should stay file-aware, including images and markdown with embedded images.
- Prefer attribute access on returned objects, for example `source.items[0].content` and `draft.output`.
- Use `generate(..., cache=...)` for repeated generation memoization.
- Use `generate(..., tools=[...])` only when you want explicit bounded tool use inside one generation call.
- Use `output(type="cache", ...)` for named retrievable artifacts.
- Use the host-provided `date` object for date helpers such as `date.today()` and `date.today("YYYYMMDD")`.
- Inspect the authoring contract before guessing capability arguments or return shapes.

Example:

```python
source = await retrieve(type="file", ref="notes/*.md")
latest_three = sorted(
    [item for item in source.items if item.exists],
    key=lambda item: item.metadata.get("mtime_epoch") or 0,
    reverse=True,
)[:3]
await output(
    type="cache",
    ref="research/latest-note-summary",
    data="\n\n".join(item.content for item in latest_three),
    options={"mode": "replace", "ttl": "24h"},
)

cached = await retrieve(type="cache", ref="research/latest-note-summary")

draft = await generate(
    prompt=(
        "Write a short summary of these notes.\n\n"
        + cached.items[0].content
    ),
    instructions="Be concise and factual.",
    tools=["web_search_tavily"],
    model="gpt-mini",
    cache="daily",
)

await output(
    type="file",
    ref=f"reports/summary-{date.today()}.md",
    data=draft.output,
    options={"mode": "replace"},
)
```

Multimodal file inputs use the shared host prompt builder:

```python
image = await retrieve(type="file", ref="images/test_image.jpg")

caption = await generate(
    prompt="Describe this image in one short paragraph.",
    inputs=image.items,
)
```

```python
note = await retrieve(type="file", ref="notes/trip-report.md")

summary = await generate(
    prompt="Summarize this note, taking both the text and embedded images into account.",
    inputs=note.items,
    instructions="Be concise and factual.",
)
```
