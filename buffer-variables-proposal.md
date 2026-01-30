# Buffer Variables Proposal (Virtualized I/O)

## Goal
Introduce **named in-memory buffers** that can be used in place of files across workflows, context templates, and tools. The same directives and tool syntax should work with either files or buffers to keep design consistent and reduce surface area.

## User Syntax (parameter-based)
Use a `variable` parameter instead of a file path.

Examples:
```
@output-file (variable=summary)
@input-file (variable=summary)
@tools url_import(variable=source_dump)
```

## Core Semantics
- **Default remains stateless**: no buffers unless explicitly used.
- **Buffers are run-scoped by default** (ephemeral, no persistence).
- Buffers can be **written** or **read** wherever file I/O is supported.
- Future: optional persistent buffers (e.g., `scope=persistent`) without implying durable sessions.

## Validation Rules
- If `variable` is set, **path must be omitted** (error on both).
- If `variable` is missing or invalid, return a directive error.
- `@input-file (variable=name)`:
  - If missing, either skip the step (like `(required)`) or inject a clear "missing buffer" marker (policy TBD).
- `@output-file (variable=name)`:
  - Honors existing write mode (append/new/replace) if applicable.

## Buffer Store (internal)
- Run-scoped in-memory store: `name -> {content, metadata}`
- Minimal API:
  - `put(name, content, mode=replace|append, metadata={})`
  - `get(name)`
  - `list()`
  - `clear(name)` / `clear_all()`

## Integration Points
1. **Directives**
   - Extend `@output-file` and `@input-file` parsing to accept `(variable=name)`.
   - Use the buffer store when `variable` is present.

2. **Tools**
   - Tools may accept `variable` parameters to write outputs into buffers (e.g., `url_import(variable=...)`).
   - Optional: allow tools to read from buffers when they currently read from files.

3. **Workflow Engine + Context Manager**
   - Both engines should use the same directive handling to keep behavior aligned.
   - Enables cross-step state passing without file I/O.

## Search + Buffers (outline)
- `file_ops_safe.search(..., variable=results_var)` writes structured results to a buffer instead of inlining.
- Add buffer exploration tools: `peek`, `filter`, `read`, `export`.
- Optional directive sugar: `@input-file (variable=results_var, select=...)` to inline a subset.

## Future-Friendly Extensions (RLM / Large-Input Exploration)
Buffers provide a foundation for REPL-like tools:
- `buffer.search(name, query, top_k)`
- `buffer.read(name, offset, length)`

This enables iterative exploration of large content without stuffing it into a single prompt.

## Decisions & Notes (on-the-fly)
- **Terminology**: BufferStore is the container; entries are called **variables** in user-facing syntax.
- **paths-only remains**: we did not rename to ref-only; use `paths-only` to avoid inlining buffer content.
- **write-mode**: added explicit `replace` for destructive writes.
  - Buffers default to **append**; use `replace` to overwrite.
  - `new` still supported for experimental context templates.
- **Context templates**: now stateless by default; no implicit prior-output chaining.
- **Logging**: activity.log now includes input/output resolution for variables.

## Open Questions
- Missing-buffer behavior: skip step vs explicit placeholder.
- Size limits (bytes/tokens) and defaults.
- Persistent buffer scope: name/namespace + TTL policy.
- Logging policy (names/sizes only to avoid leaking content).


## Implementation Steps (concrete)
1. **Add BufferStore** ✅
   - New module: `core/runtime/buffers.py`
   - API: `put(name, content, mode="replace|append", metadata={})`, `get(name)`, `list()`, `clear(name)`, `clear_all()`

2. **Plumb run deps** ✅
   - Add `buffer_store` to `ChatRunDeps` in `core/llm/chat_executor.py`.
   - Create a `BufferStore` per chat run and pass via `deps` to `agent.run(...)`.
   - For workflows, add a run-scoped BufferStore in `workflow_engines/step/workflow.py` context.

3. **Directive parsing: parameter-only values** ✅
   - Update `DirectiveValueParser.parse_value_with_parameters(...)` to accept values like `(variable=foo)` when allowed.

4. **InputFileDirective: variable support** ✅
   - `core/directives/input_file.py`: allow `(variable=...)` parameter.
   - If `variable` is present, read from `buffer_store` in directive context and return a virtual file entry (`filepath: variable:<name>` + content).
   - Missing buffer with `required=true` -> existing skip signal.

5. **OutputFileDirective: variable target** ✅
   - `core/directives/output_file.py`: allow `(variable=...)` parameter.
   - If `variable` is present, return a structured target (e.g., `{"type": "buffer", "name": var}`) instead of a file path.

6. **Directive pipeline: pass buffer_store** ✅
   - `core/workflow/parser.py`: pass `buffer_store` through `process_step_content(..., buffer_store=...)` and into `registry.process_directive(...)`.
   - `core/context/manager.py`: when processing `@input-file` directives, pass `buffer_store` via `registry.process_directive(...)`.

7. **Workflow engine: write to buffer targets** ✅
   - `workflow_engines/step/workflow.py`:
     - Detect output targets that are buffers.
     - Use `BufferStore.put(...)` instead of filesystem writes.
     - Respect `@write-mode` (append/new/replace) semantics for buffers.

8. **Context manager: full @output-file support** ✅
   - Honor `@output-file` for buffers and filesystem writes.
   - Support `@write-mode` and `@header` directives when writing files.
   - Remove hardcoded cross-step context passing (stateless by default).

9. **Tool support (optional, staged)**
   - Extend tools to accept `variable` params and use `RunContext.deps.buffer_store` when present.
   - Start with `file_ops_safe.search(..., variable=...)` to store structured results.

10. **Documentation + Validation**
   - Update docs: directives reference + examples for `(variable=...)`.
   - Add validation scenario covering:
     - buffer read/write in workflow steps
     - input-file variable required/optional behavior
     - search-to-buffer tool path
