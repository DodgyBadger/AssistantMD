# Context Manager Refactor Plan

## Goals
- Reduce complexity of `core/context/manager.py` without changing behavior.
- Improve testability by isolating logic into smaller units.
- Make section execution flow easier to read and debug.

## Non-Goals
- No behavioral changes unless explicitly requested.
- No public API changes for templates/directives.

## Proposed Phases

### Phase 0: Safety Net
- Add a lightweight regression scenario for context manager execution if one does not exist.
- Capture expected artifacts for a representative template (inputs, tools, cache, output routing).

### Phase 1: Extract Helpers (No Behavior Change)
- Extract prompt construction from `manage_context` into `build_manager_prompt(...)`.
- Extract tools resolution into `resolve_section_tools(...)`.
- Extract input processing into `resolve_section_inputs(...)` returning:
  - `input_file_data`, `context_input_outputs`, `skip_reason`.
- Extract cache decision logic into `resolve_section_cache(...)` returning:
  - cache hit/miss, cached output, cache metadata, and a write-back hook.
- Extract output routing into `route_section_output(...)` to handle:
  - context injection, buffer/file output, persistence logging.

### Phase 2: Structure the Section Flow
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

## Deliverables
- Smaller, focused helpers with clear boundaries.
- A section runner that keeps the main loop compact.
- Behavior preserved, verified by tests.

## Risks
- Subtle ordering dependencies in the current code path.
- Cache semantics may be sensitive; keep Phase 1 purely extractive.

## Suggested Next Step
- Start Phase 1 with prompt and tools extraction first (lowest risk), then input resolution.
