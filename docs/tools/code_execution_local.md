# `code_execution_local`

## Purpose

Run constrained local Python against the current chat session and current AssistantMD runtime.

## Tool Argument

- `code`: constrained Python snippet to execute

## The Monty Runtime

This tool does not run CPython. It runs **Monty** — a Python interpreter written in Rust with its own bytecode VM. 
Understanding what Monty is and is not will save you from writing code that looks valid but fails at runtime.

Monty is a script executor, not an interactive REPL. Your final line should be an explicit expression that evaluates to the value you want to return. Do not rely on implicit printing.

### What Monty supports

- Functions (sync and async), closures, comprehensions, f-strings, type hints
- Standard library: `sys`, `typing`, `asyncio`, `pathlib`
- External function calls — the mechanism behind all host helpers
- Dataclasses defined on the host (the helper result types are available as typed objects)
- Type checking via `ty` bundled in the binary — wrong helper calls are caught before execution

### What Monty does not support

- **No class definitions** — you cannot define classes inside the script
- **No match statements**
- **No context managers** — `with` statements are not supported
- **No third-party packages** — do not attempt to import anything that is not listed above
- **Not a REPL** — each execution starts with a clean slate; functions and values from previous runs are not available

When you find yourself reaching for something outside this list, simplify the approach rather than adding imports or boilerplate.

### Type checking

The runtime runs `ty` on your code before execution using type stubs for all helpers. If you pass wrong argument types or unknown keyword arguments to a helper, execution will not start and you will get a type error instead of a runtime failure.

## Runtime Surface

Scope comes from the active chat session:

- file and history access come from the enabled tool surface
- tool access mirrors the enabled chat tools, excluding `code_execution_local` itself

Available helpers and the reserved `date` input:

- `call_tool(...)`: invoke one already-enabled chat tool from inside the script
- `pending_files(...)`: filter a file result set to the pending subset and explicitly complete the items you finished
- `generate(...)`: run one explicit model call, optionally with file-backed inputs or bounded tool use
- `assemble_context(...)`: build structured message history for downstream chat-style generation
- `read_cache(...)`: open one cached oversized tool result by cache ref inside the current chat session
- `parse_markdown(...)`: turn markdown into frontmatter, sections, headings, code blocks, and image refs
- `finish(...)`: end the script intentionally with a `completed` or `skipped` terminal status
- `date`: resolve common date tokens — `date.today()`, `date.this_week()`, etc.; pass `fmt` for strftime formatting

Use ordinary Python for filtering, sorting, selection, and control flow around those helpers.

## Helper Notes

### `read_cache`

- use this when chat reports that an oversized tool result was stored in a cache ref
- reads cached content for the current chat session only
- check `artifact.exists` before accessing `artifact.content`

### `pending_files`

- `operation="get"` filters a `file_ops_safe` result down to the pending subset
- `operation="complete"` marks only the items you actually finished processing

### `generate`

- tool use is opt-in — omit `tools` for plain generation
- prefer tool-first access patterns; keep `generate(...)` focused on the actual model call

### `call_tool`

- can only call tools already enabled for the chat run
- `code_execution_local` itself is excluded to prevent recursive self-invocation
- prefer branching on `result.metadata` when the tool returns structured status

### `assemble_context`

- for conversation history, fetch explicit messages through `memory_ops` and pass them as `history`
- `latest_user_message` is an explicit optional argument; it is not injected automatically

### `parse_markdown`

- returns typed objects with attributes — use `heading.text`, not `heading.get("text")`
- prefer this over regex or manual string parsing for any markdown or extracted article text

### `finish`

- only supported status values: `completed`, `skipped`
- keyword-only — `await finish(status="skipped", reason="...")`
- the script result should be the last expression or an explicit `await finish(...)`

### `date`

- resolves the same shared date tokens used elsewhere in AssistantMD
- pass `fmt` to control formatting using strftime — e.g. `date.today("%Y-%m-%d")`
- week-based values honour the current workflow or runtime `week_start_day`

## Common Patterns

### Explore a large web extraction

Extracts a page, parses the structure, pulls a target section, and returns a compact summary.
Uses `read_cache` first so re-running the script does not repeat the extraction call.

```python
code_execution_local(
    code="""
# Read from cache if the extraction was already stored
artifact = await read_cache(ref="tool/tavily_extract/call_abc123")
if not artifact.exists:
    result = await call_tool(
        name="tavily_extract",
        arguments={"urls": ["https://example.com/article"]},
    )
    parsed = await parse_markdown(value=result.output)
else:
    parsed = await parse_markdown(value=artifact.content)

# Orient: what sections does this page have?
headings = [h.text for h in parsed.headings[:20]]

# Pull the section we care about
target = next(
    (s for s in parsed.sections if "methodology" in s.heading.lower()),
    None,
)

{
    "today": date.today("%Y-%m-%d"),
    "headings": headings,
    "target_section": target.content[:1500] if target else "NOT_FOUND",
}
""",
)
```

### Process a batch of pending vault files

Lists a directory, filters to the pending subset, reads and parses each file, then marks the
processed items complete. Batches to a small slice to stay within a single execution.

```python
code_execution_local(
    code="""
listed = await call_tool(
    name="file_ops_safe",
    arguments={"operation": "list", "target": "inbox"},
)
pending = await pending_files(
    operation="get",
    items=listed,
)

if not pending.items:
    await finish(status="skipped", reason="no pending files")

results = []
selected = pending.items[:5]
for item in selected:
    doc = await call_tool(
        name="file_ops_safe",
        arguments={"operation": "read", "target": item.ref},
    )
    parsed = await parse_markdown(value=doc.output)
    results.append({
        "ref": item.ref,
        "title": parsed.frontmatter.get("title", item.ref),
        "sections": [s.heading for s in parsed.sections],
    })

await pending_files(
    operation="complete",
    items=selected,
)

results
""",
)
```

## Notes

- Helpers are injected for you - you do not need to import anything.
- file, memory, and web access should generally go through `call_tool(...)`
- Always return a value or `await finish(...)` — do not rely on side effects alone
- cached oversized tool results are available through `read_cache(ref=...)`
- If a cached tool result already exists, use `await read_cache(ref="...")` instead of re-running the source tool
- Some pages add wrapper headings such as extraction banners, navigation, or TOC chrome — prefer the article's real prose sections over page furniture
- prefer returning a compact final value instead of printing large text
