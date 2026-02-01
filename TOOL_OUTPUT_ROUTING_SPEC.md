# Tool/Directive Output Routing (Spec)

## Goal
Provide a single, flexible routing model for **tool outputs** and **directive outputs**
so users can decide where content goes (inline, buffer variable, or file) without
adding new concepts.

This applies equally to **workflows** and the **context manager**. The same rules,
syntax, and mental model must hold in both.

This spec introduces a common `output=...` parameter that can be attached to:
- `@tools` (per-tool)
- `@input` (any input source)
- future input sources (e.g., `url:`)

No combinations are disallowed by policy; the system should allow all combinations
even if they are unusual, because they can enable useful workflows (e.g., file→file
aggregation).

## Syntax

### 1) Tools (per-tool params only)
```
@tools web_search_tavily(output=variable:foo), code_execution(output=file:results/{today})
```

Rules:
- `output=...` is attached to **each tool token**.
- No directive-level/global `output=` for the entire `@tools` line to avoid ambiguity.
- Commas and line breaks are allowed for readability as long as each tool token
  is complete.

### 2) Directives (input)
```
@input file:myfile (output=variable:foo)
@input variable:foo (output=file:myfile)
@input file:myfile2 (output=variable:foo)     # append by default
@input url:https://example.com (output=variable:foo)  # future input source
```

Rules:
- `output=...` is optional.
- If absent, existing behavior applies (inline content in the prompt).

## Destinations
Supported destination values for `output=`:
- `inline` (default behavior)
- `variable:NAME`
- `file:PATH`
- `discard` (optional; no inline + no storage)

## Routing Semantics

### Tools
When a tool returns output:
1) If the tool token includes `output=...`, route the tool result there.
2) Otherwise, keep current behavior (inline tool result).
3) Explicit `output=inline` is a hard rule (no routing allowed).
4) Absence of `output=...` allows LLM discretion **if instructed** (default remains inline).
5) Tool tokens may include `write-mode=append|replace|new` to control how routed
   outputs are written (defaults to append when routing is enabled).
6) Streaming tool result events should emit the **manifest**, not the full payload,
   when routing is enabled.

### Multiple @tools directives (aggregation)
- Support multiple `@tools` directives in the same step/section.
- All tool tokens across those directives are **aggregated** and enabled.
- This applies to **workflow steps** and **context manager sections**.
- If the same tool appears multiple times, the last `output=...` parameter wins
  for that tool in that step/section.

### @input
When `@input` has `output=...`:
- The data that would have been inlined is routed to the destination instead.
- The prompt should include a compact **manifest** (not full content) so the LLM
  knows the operation occurred.
- `write-mode=append|replace|new` can be used alongside `output=...` for explicit control;
  defaults to append.

### LLM Skip (explicit)
- Use `@model none` to skip LLM execution for a step/section.
- Applies equally to **workflows** and **context manager** sections.
- No implicit auto-skip; directives still run, but the model is not invoked.
- The manifest should include:
  - count of items
  - destination
  - total size (chars)
  - filenames/paths if available

Example manifest:
```
[input routed] 3 files -> variable:foo (total 12,340 chars)
paths: notes/2026-01-01, notes/2026-01-02, notes/2026-01-03
```

## Write Mode
Routing respects existing write-mode semantics:
- `variable:` default is **append**, unless `write-mode=replace`.
- `file:` default is **append**, unless `write-mode=replace` or `write-mode=new`.

This enables patterns like:
```
@input file:myfile1 (output=variable:foo)      # append
@input file:myfile2 (output=variable:foo)      # append
@input file:myfile3 (output=variable:foo, write-mode=replace)
```

## Validation / Parsing Rules
- Allow all combinations (file→file, variable→variable, variable→file, file→variable).
- If destination is invalid (e.g., missing name/path), return a directive/tool error.
- If `output=inline`, behave exactly as today (inline content).

## Future-Ready
This model should work for new input sources without changes:
- `@input url:... (output=variable:foo)`
- `@input query:... (output=file:...)`

## Buffer Ops Tool (LLM access)
Routing tool output to buffers is only useful if the LLM can read those buffers.
Define a dedicated tool (e.g. `buffer_ops`) for controlled buffer access.
Keep the call shape aligned with `file_ops_safe`:
- `operation=...` is required
- `target` is used similarly to file ops (buffer name for most ops)
- `scope` can be used to disambiguate (e.g., for `search`, set `scope` to the buffer name)

Minimum actions (REPL-style):
- `list` — list buffer names + sizes
- `info` — metadata for a single buffer (size, created_at, updated_at, source)
- `peek` — preview content with `offset` + `max_chars`
- `read` — **range-based** read (required: `start` + `end` line numbers or `offset` + `length`)
  - If a full read is requested or the range exceeds size limits, return a clear error message.
- `search` — regex/substring search returning matches + context
- `export` — write buffer to file path (vault-relative)

Example usage:
```
buffer_ops(operation="list")
buffer_ops(operation="info", target="search_results")
buffer_ops(operation="peek", target="search_results", offset=0, max_chars=1000)
buffer_ops(operation="read", target="search_results", start_line=1, end_line=200)
buffer_ops(operation="search", target="TODO", scope="search_results")
buffer_ops(operation="export", target="search_results", destination="reports/search_results.md")
```

## Examples

### Tools
```
@tools web_search_tavily(output=variable:search_results),
       code_execution(output=variable:analysis)
```

### Inputs
```
@input file:myhugefile.md (output=variable:huge_file)
@input variable:huge_file (output=file:archive/{today})
```

## Implementation Plan (Concrete Steps)

1) **Refactor directive helpers into utils (cleanup first)** ✅
   - Move helper-style modules into `core/utils/` to reduce `core/directives` sprawl:
     - `pattern_utilities.py` → `core/utils/patterns.py`
     - `file_state.py` → `core/utils/file_state.py`
     - (optional) `parser.py` shared pieces → `core/utils/directive_parsing.py`
   - Keep directive classes + registry/bootstrap in `core/directives/`.
   - Update imports in `@input`, `@output`, and any pattern/state consumers.

2) **Add routing helpers (single source of truth)** ✅
   - Create `core/utils/routing.py` (or similar) with:
     - `parse_output_target(...)` (supports `inline|discard|variable:|file:`)
     - `normalize_write_mode(...)` (reuse `WriteModeDirective`)
     - `write_output(...)` (buffer/file routing w/ write-mode)
     - `build_manifest(...)` (compact inline notice for routed outputs)

3) **Extend @tools parsing (per-tool params)** ✅
   - Update `ToolsDirective` to parse tool tokens with parameters:
     - `web_search_tavily(output=variable:foo, write-mode=replace)`
   - Aggregate multiple `@tools` directives (per spec).
   - For each tool, wrap the tool function to support `output` + `write-mode`.

4) **Tool routing wrapper** ✅
   - Implement a wrapper that:
     - Calls the underlying tool (string output)
     - Routes output per explicit rule (or LLM-chosen when allowed)
     - Stores content in buffer/file
     - Returns a manifest string when routed (instead of full output)

5) **@input routing** ✅
   - Allow `output=` + `write-mode=` parameters on `@input`.
   - If `output=` is present, route the content and inject only a manifest.
   - Default behavior stays unchanged when no `output=` is provided.

6) **Add buffer_ops tool**
   - Implement `buffer_ops` with `operation=...` shape aligned to `file_ops_safe`.
   - Provide REPL-style access: `list`, `info`, `peek`, `read` (range-based), `search`, `export`.

7) **Unify write behavior**
   - Replace ad-hoc file/buffer writes in:
     - `workflow_engines/step/workflow.py`
     - `core/context/manager.py`
   - Use shared helpers from `core/utils/routing.py` or a dedicated writer.

8) **Docs + validation**
   - Update directive reference and examples.
  - Add validation scenarios for:
    - tool output routing to variable/file
    - `@input` output routing
    - buffer_ops range reads + size errors

## Constants
- Add size limits for buffer reads and routed payloads to `core/constants.py`.
- Keep these limits internal for now (not user-facing settings).
