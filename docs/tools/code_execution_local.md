# `code_execution_local`

## Purpose

Run constrained local Python in AssistantMD's Monty runtime.

This document serves two purposes:

- it documents the chat tool `code_execution_local`, which runs a snippet against the current chat session
- it is also the main helper reference for authored workflows and context assembly scripts, which run in the same Monty environment without the outer tool wrapper

## Tool Argument

- `code`: constrained Python snippet to execute

## The Monty Runtime

This tool does not run CPython. It runs **Monty** — a Python interpreter written in Rust with its own bytecode VM.

Monty is actively developed upstream, so AssistantMD documents the subset it intentionally supports for authoring rather than every Monty VM feature. Treat the type checker and compile step as the source of truth for the exact runtime available in the current installation.

Monty runs each AssistantMD script as a fresh script execution. Your final line should be an explicit expression that evaluates to the value you want to return. Do not rely on implicit printing.

### Supported Authoring Pattern

AssistantMD examples and validation scenarios stay within this subset:

- ordinary expressions, assignments, loops, conditionals, comprehensions, and helper function definitions
- async helper calls using `await`
- f-strings and type hints where they help readability
- common imports used by AssistantMD examples, including `json`, `sys`, `typing`, `asyncio`, and `pathlib`
- host-provided dataclasses and helper result objects, such as `RetrievedHistoryResult`, `HistoryMessage`, `ToolExchange`, and `LatestMessage`
- external function calls through AssistantMD helpers and direct tools, such as `file_ops_safe(...)`, `delegate(...)`, and `assemble_context(...)`
- pre-execution type checking with Monty's bundled `ty` integration

### Authoring Guardrails

- Do not define custom classes in authored scripts; use dictionaries, lists, helper result objects, and small functions.
- Do not depend on arbitrary standard-library modules; stick to modules used in AssistantMD examples unless you have compiled the script successfully in this environment.
- Do not import third-party packages; use AssistantMD helpers for file access, model calls, history, and tool calls.
- Do not depend on state from previous script executions; pass state through files, caches, or explicit helper results.
- If a Python construct matters to your script and is not shown in AssistantMD examples, compile the script before relying on it.

When you find yourself reaching for something outside this list, simplify the approach rather than adding imports or boilerplate.

### Type checking

The runtime runs `ty` on your code before execution using type stubs for all helpers. If you pass wrong argument types or unknown keyword arguments to a helper, execution will not start and you will get a type error instead of a runtime failure.

## Runtime Surface

The Monty helper surface is shared across chat-side execution, workflows, and context scripts.

Scope comes from the current runtime context:

- in chat, file and history access come from the active session and the tools enabled for that run
- in authored workflows and context scripts, access comes from the current script host and whatever tools/helpers that runtime exposes

Available helpers and reserved inputs:

- direct tool functions such as `file_ops_safe(...)`, `delegate(...)`, `browser(...)`, or `tavily_extract(...)`: invoke a tool by name with keyword arguments
- `pending_files(...)`: filter a file result set to the pending (unprocessed) subset and explicitly complete the items you finished
- `retrieve_history(...)`: read broker-owned conversation history as safe atomic units
- `assemble_context(...)`: build structured message history for downstream chat-style generation
- `read_cache(...)`: open one cached oversized tool result by cache ref inside the current runtime context
- `parse_markdown(...)`: turn markdown into frontmatter, sections, headings, code blocks, and image refs
- `finish(...)`: end the script intentionally with a `completed` or `skipped` terminal status
- `date`: resolve common date tokens — `date.today()`, `date.this_week()`, etc.; pass `fmt` for strftime formatting
- `latest_message`: read-only latest message metadata for context script decision making

Use ordinary Python for filtering, sorting, selection, and control flow around those helpers.

## Helper Notes

### `read_cache`

- use this when chat reports that an oversized tool result was stored in a cache ref
- reads cached content for the current runtime context; in chat that means the current chat session
- check `artifact.exists` before accessing `artifact.content`

### `pending_files`

- `operation="get"` filters a `file_ops_safe` result down to the pending subset
- `operation="complete"` marks only the items you actually finished processing

### Direct Tool Calls

- call tools by their configured names, for example `await file_ops_safe(operation="read", path="notes/example.md")`
- `code_execution_local` itself is excluded to prevent recursive self-invocation
- direct tool results expose `output`, `metadata`, `content`, and `items`
- prefer branching on `result.metadata` when the tool returns structured status

### `assemble_context`

- for conversation history, fetch explicit messages through `retrieve_history(...)` and pass `history.items`
- `retrieve_history(...)` counts safe history units: user message = 1, assistant message = 1, matched tool call + return = 1 `ToolExchange`
- `retrieve_history(...)` items are structured objects; slice, remove, or reorder those objects when curating context, then pass the remaining objects back to `assemble_context(...)`
- use `item.text` or `history.text` when you intentionally need clean prompt text for `delegate(...)`; this omits provider-native payload fields while preserving the original object for assembly
- in context assembly scripts, use read-only `latest_message` only to decide what prior history, files, or instructions to include
- do not add `latest_message` to `history` or `context_messages`; the chat runtime appends it exactly once after your assembled context
- use `latest_message.exists`, `latest_message.role`, `latest_message.content`, and `latest_message.text` when context selection should depend on the active request

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

### Chat tool invocation

Use the outer `code_execution_local(...)` wrapper only when calling the chat tool directly.

```python
code_execution_local(
    code="""
{
    "today": date.today("%Y-%m-%d"),
    "tomorrow": date.tomorrow("%Y-%m-%d"),
}
""",
)
```

### Raw Monty script for authored files

Inside a workflow or context script, write only the Python script body. Do not wrap it in `code_execution_local(...)`.

```python
history_result = await retrieve_history(scope="session", limit="all")

await assemble_context(
    history=history_result.items,
    instructions="Keep the answer concise.",
)
```

### Branch on the active chat message

Use `latest_message` for context selection, not for manual message insertion.

```python
history_result = await retrieve_history(scope="session", limit="all")
context_messages = []

if latest_message.exists and "trigonometry" in latest_message.text.lower():
    guide = await file_ops_safe(operation="read", path="Projects/trig/study-guide.md")
    if guide.metadata.get("status") == "completed":
        context_messages.append({"role": "system", "content": guide.output})

await assemble_context(
    history=history_result.items,
    context_messages=context_messages,
)
```

### Explore a large web extraction

Extracts a page, parses the structure, pulls a target section, and returns a compact summary.
Uses `read_cache` first so re-running the script does not repeat the extraction call.

```python
code_execution_local(
    code="""
# Read from cache if the extraction was already stored
artifact = await read_cache(ref="tool/tavily_extract/call_abc123")
if not artifact.exists:
    result = await tavily_extract(urls=["https://example.com/article"])
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
listed = await file_ops_safe(operation="list", path="inbox")
pending = await pending_files(
    operation="get",
    items=listed,
)

if not pending.items:
    await finish(status="skipped", reason="no pending files")

results = []
selected = pending.items[:5]
for item in selected:
    doc = await file_ops_safe(operation="read", path=item.ref)
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
- Standard-library imports such as `import json` are fine when needed.
- file, memory, and web access should generally go through direct tool calls or dedicated helpers
- Always return a value or `await finish(...)` — do not rely on side effects alone
- cached oversized tool results are available through `read_cache(ref=...)`
- If a cached tool result already exists, use `await read_cache(ref="...")` instead of re-running the source tool
- Some pages add wrapper headings such as extraction banners, navigation, or TOC chrome — prefer the article's real prose sections over page furniture
- prefer returning a compact final value instead of printing large text
