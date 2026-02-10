# Context Manager Refactor Plan (Revised)

## Goals
- Reduce complexity of `core/context/manager.py` without changing behavior.
- Improve testability by isolating logic into smaller units.
- Make section execution flow easier to read and debug.

## Non-Goals
- No behavioral changes unless explicitly requested.
- No public API changes for templates/directives.

## High-Level Issues
1. `build_context_manager_history_processor` mixes config loading, directive parsing, cache logic, prompt assembly, LLM invocation, output routing, persistence, and history assembly in one place.
2. Nested helpers capture state and mutate shared dicts, obscuring flow and making cache/persistence bugs likely.
3. Directive parsing patterns (`output`, `header`, `write-mode`, `recent-*`, `cache`, `tools`, `input`) are ad hoc and scattered.
4. Cache logic blends run-scope caching with persistent cache and injects “persisted” state into a run-local cache structure.
5. Input-file resolution and logging/telemetry are entangled with LLM orchestration.
6. Prompt assembly is repeated string concatenation with implicit ordering.

## Refactor Plan

### Phase 0: Safety Net ✅
- Add a lightweight regression scenario for context manager execution if one does not exist.
- Capture expected artifacts for a representative template (inputs, tools, cache, output routing).

### Phase 1: Extract Helpers (No Behavior Change) ✅
1. Extract a Template Runtime Config
- Add `ContextTemplateRuntime` with `template`, `sections`, `week_start_day`, `passthrough_runs`, `token_threshold`, `chat_instruction_message`.
- Build via `load_context_template_runtime(...)`.

2. Isolate Message Slicing and Rendering
- Move `_run_slice`, `_find_last_user_idx`, `_extract_role_and_text` to module-level helpers.
- Add `render_history(messages, runs_to_take)` returning `rendered_history`, `latest_input`, `manager_slice`.

3. Extract Input File Resolution
- Create `resolve_input_files(...)` returning `input_file_data`, `context_input_outputs`, `skip_reason`, `empty_directive`.
- Keep input-file logging and validation in one place.

4. Extract Tools Resolution
- Add `resolve_section_tools(...)` to wrap `ToolsDirective` parsing and tool-instruction generation.

5. Extract Cache Decision Logic
- Add `resolve_section_cache(...)` returning cache hit/miss, cached output, cache metadata, and a write-back hook.

6. Separate Output Routing
- Add `route_section_output(...)` to handle context injection, buffer/file output, and logging.

### Phase 2: Structure the Section Flow ✅
- Create a `ContextSectionRunner` (class or function) that:
  1. Resolves inputs
  2. Resolves tools
  3. Resolves cache
  4. Executes LLM if needed
  5. Routes outputs
  6. Emits validation events
- Ensure per-section results are returned in a structured dataclass for testing.

### Phase 3: Clean Interfaces
- Introduce internal dataclasses for clarity:
  - `InputResolutionResult`
  - `CacheDecision`
  - `SectionExecutionResult`
  - `OutputRoutingResult`
- Replace ad-hoc dicts/lists with these types in the main loop.

### Phase 4: Tests and Verification
- Add targeted unit tests for:
  - input resolution edge cases (`required`, `refs_only`, `output=context`, per-file routing)
  - cache hits/misses
  - context output header selection
- Run validation scenarios and confirm no diff in emitted artifacts.

## Recommended Order of Refactor
1. Extract module-level helpers for slicing and role/text rendering.
2. Introduce runtime config loader for templates.
3. Extract input file resolution.
4. Extract tools resolution.
5. Extract cache decision logic.
6. Separate output routing.
7. Create the section runner and wire it in.
8. Add dataclasses and replace ad-hoc dicts.
9. Add tests.

## Risks
- Subtle ordering dependencies in the current code path.
- Cache semantics are sensitive; keep Phase 1 purely extractive.
- Preserve `cache_entry["persisted"]` semantics (persist once per run).
- Ensure `@input (required)` skip logic still prevents `@output context` emits.
- Keep `passthrough_runs`, `manager_runs`, and per-section `recent-runs` semantics unchanged.
