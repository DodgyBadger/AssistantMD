# Monty Direct Tool Calls Refactor Plan

## Goal

Make authored Monty scripts call enabled tools directly by name, instead of routing through `call_tool(...)`.

This aligns the authoring surface with Pydantic AI Harness CodeMode: tools appear as ordinary Python callables inside the sandbox, while host-only authoring capabilities remain callable helpers.

## Current Problem

`call_tool(...)` was a Monty-specific translation layer. It invoked a chat tool, then collapsed the tool result into `CallToolResult(output, metadata)`.

That loses important data for multimodal tool results. For example, `file_ops_safe(read)` returns image payloads in `ToolReturn.content`, but `call_tool(...)` only preserves `ToolReturn.return_value` as text plus metadata. This breaks composition with `generate(inputs=...)`, which expects structured source artifacts.

## Target Contract

Monty scripts should call tools and helpers using the same direct function style:

```python
image = await file_ops_safe(operation="read", path="Math/page_images/page-1.png")
draft = await generate(prompt="Review this page.", inputs=image.items)
history = await retrieve_history(scope="session", limit="all")
```

Tool-like callables should return a non-lossy script-facing result object:

- `output`: human-readable return value.
- `metadata`: structured host/tool metadata.
- `content`: raw tool payload when present, including multimodal content.
- `items`: normalized `RetrievedItem` source artifacts when the result can be reused by downstream helpers.

Helpers that already return specialized types can keep doing so. The stable authoring contract is the callable name and keyword signature, not whether the implementation is a helper, wrapped tool, or future Pydantic AI Harness capability.

## Design Principles

- Tools are LLM-facing capabilities, but selected tools can also be exposed as direct Monty callables.
- Helpers are script-native capabilities such as `generate`, `retrieve_history`, `assemble_context`, `pending_files`, `parse_markdown`, `read_cache`, and `finish`.
- Avoid a generic `call_tool(...)` as the primary scripting abstraction.
- Preserve tool outputs faithfully; do not flatten multimodal payloads into text-only envelopes.
- Keep Pydantic AI compatibility in mind: direct callable tools, standard tool validation, nested call/return observability, and native multimodal flow.

## Implementation Steps

1. Add a direct-tool registration path to the Monty authoring host.
   - Resolve enabled tools for the current script host.
   - Expose each selected tool as a Python-safe callable name.
   - Reuse the existing tool binding and argument validation path where possible.

2. Add a script-facing tool result type.
   - Replace `CallToolResult` with a non-lossy script-facing result object.
   - Preserve `ToolReturn.content`.
   - Preserve metadata.
   - Add `items` projections for content-producing results.

3. Implement file result projection first.
   - `file_ops_safe(read text/markdown)`: one `RetrievedItem` with content and source path metadata.
   - `file_ops_safe(read image)`: one file-backed `RetrievedItem` with source path and media metadata.
   - `file_ops_safe(list/search/frontmatter)`: path-backed items where metadata exposes paths cleanly.
   - Status/write operations: empty `items`.

4. Update `generate(inputs=...)` composition.
   - Keep accepting `RetrievedItem` / `RetrieveResult` / sequences.
   - Ensure direct tool results compose via `.items`, not by passing the whole result object.

5. Remove `call_tool(...)` from the preferred authoring surface.
   - Update stubs and helper docs so direct tool functions are taught first.
   - Remove `call_tool(...)` from the registered helper surface.
   - Since this branch is not merged, existing vault scripts and validation fixtures can be updated directly.

6. Update scripts and validation scenarios.
   - Replace `await call_tool(name="file_ops_safe", arguments={...})` with `await file_ops_safe(...)`.
   - Exercise direct file read to `generate(inputs=result.items)` for text, markdown-with-images, and direct image inputs.
   - Keep a regression for multimodal payload preservation.

7. Reassess Pydantic AI Harness adoption.
   - The local environment currently has `pydantic_ai` but not `pydantic_ai_harness`.
   - Online CodeMode docs and source show the desired architecture: direct sandbox callables, nested tool metadata, and native multimodal return handling.
   - After this refactor, evaluate whether our custom host can be replaced by or layered on Harness CodeMode.

## Validation Targets

- A Monty script can call `file_ops_safe(...)` directly.
- Direct image reads preserve enough data for `generate(inputs=image.items)`.
- Markdown reads preserve source path metadata so embedded images are resolved and interleaved by the prompt builder.
- Text reads still work with `parse_markdown(value=file.items[0])` and `generate(inputs=file.items)`.
- Existing workflow/context scenarios pass after replacing `call_tool(...)` usage.
- Logfire/validation events still show nested tool activity clearly.

## Implementation Status

- Direct tool callables are now registered into the Monty runtime from the configured tool set, excluding recursive `code_execution`.
- Script-facing tool results now expose `output`, `metadata`, `content`, and `items`.
- `file_ops_safe` projections cover read/list/search/frontmatter/head; web/browser-style tools project aggregate text items.
- Seed templates, validation scenarios, and local vault authoring scripts use direct tool calls instead of `call_tool(...)`.
- `call_tool(...)` has been removed from the registered helper surface.

## Open Questions

- Should every direct tool result use the same result class, or should tools be allowed to return domain-specific result classes?
- How closely should the implementation mirror Pydantic AI Harness CodeMode internals versus only matching its authoring contract?
