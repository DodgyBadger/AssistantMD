# Monty Tool Boundary Refactor Plan

## Goal

Refactor the Monty authoring surface toward a clearer long-term boundary:

- tools remain the primary access layer for files, search, browser, extraction, and other external operations
- Monty remains the orchestration layer for Python control flow and explicit model calls
- host helpers are kept only for genuinely host-owned semantics that tools cannot express cleanly

The target is a design that is:

- flexible enough for agent-authored workflows and context templates
- easier for an authoring LLM to learn and use correctly
- more observable in logs than an everything-through-`code_execution_local` model
- less prone to helper creep and hidden runtime magic

This effort is happening on an experimental dev branch. Backward compatibility with existing experimental Monty workflows and templates is not a constraint. Prefer a clean target design over compatibility shims.

## Current Assessment

The current Monty surface is workable, but it mixes three patterns:

1. tool-style access through `call_tool(...)`
2. convenience access through helpers like `retrieve(...)` and `output(...)`
3. host-native orchestration helpers like `generate(...)`, `assemble_context(...)`, `parse_markdown(...)`, `finish(...)`, and `complete_pending(...)`

This middle state is usable, but the boundaries are blurry:

- file access semantics are duplicated between helpers and file tools
- context-template history currently relies on partially magical runtime inputs
- pending processing is workflow state, not simple file access, but today it still starts from `retrieve(...)`
- every new need raises the same question: tool, helper, or template/frontmatter magic

## Recommended Direction

Adopt a tool-first access model with a narrower, deliberate Monty helper surface.

### Default Rule

- If the capability is ordinary access to content or an external operation, prefer a tool.
- If the capability is a host-owned runtime concept that pure tools cannot model cleanly, use a helper.

### Keep as Monty Helpers

- `generate(...)`
- `assemble_context(...)`
- `parse_markdown(...)`
- `finish(...)`
- a refactored pending helper family for workflow-state semantics only

### Prefer Tools For

- file listing, searching, and reading
- file writes and mutations when direct file ops are needed
- web search, extraction, browser usage, crawl
- workflow execution
- memory and conversation-history retrieval

### Avoid

- broadening `retrieve(...)` into a second file/query DSL
- frontmatter-bound object systems that recreate DSL behavior via schema and interpolation
- hidden context-template-only globals unless there is no cleaner explicit contract

### Remove if They Do Not Fit the New Boundary

- `retrieve(type="file", ...)`
- `output(type="file", ...)`
- any helper that duplicates ordinary tool mechanics rather than expressing host-native semantics

## Architecture Decision

### Chosen Baseline

Move toward:

- tools for access
- Python for orchestration
- helpers for host-native semantics only

This is preferable to both extremes:

- helper-heavy Monty as a full product DSL in Python
- fully frontmatter-bound inputs with implicit runtime objects

### Why This Wins

- Better observability: top-level tool usage remains visible in logs
- Better transferability: closer to the broader code-mode/tool-wrapping model
- Easier LLM instruction: one durable rule about when to use tools vs helpers
- Lower drift risk: avoids rebuilding large slices of `file_ops_*` semantics in Monty
- Keeps room for product-native primitives where they genuinely help

## Open Design Questions

### 1. File Access Helpers

Decide whether to:

- keep them as convenience wrappers for common file/cache access
- or remove them so that file access is expected to go through tools

Recommendation:

- remove helper-based file access if it does not fit the target boundary
- do not preserve it for compatibility reasons
- use tools for file discovery/read/write and keep helpers focused on host-owned runtime semantics

### 2. Pending Workflow Semantics

Pending is not ordinary file access. It is workflow state.

Options:

- keep `complete_pending(...)` as the narrow host-native acknowledgment helper
- or redesign pending around a single helper family with explicit selection/completion operations
- do not revert to implicit “retrieved means processed” behavior

Recommendation:

- redesign pending as a dedicated helper surface, likely with operations such as:
  - `pending.get(...)`
  - `pending.complete(...)`
- treat pending as a filter/state layer over file results, not as ordinary file retrieval
- keep completion explicit
- do not treat pending as a file selector that silently mutates state on success

### 3. Context Template Conversation State

Current context-template Monty runs rely on injected conversation state and/or retrieval patterns that are not yet documented clearly enough.

Options:

- explicit runtime inputs for context templates
- run-history retrieval through a dedicated tool
- hidden globals

Recommendation:

- move conversation/history access toward a dedicated `memory_ops` tool
- design `memory_ops` for both chat use and scripted Monty use
- avoid hidden globals and split-path history semantics
- keep context templates explicit about how they obtain history/state

### 4. Conversation Storage Direction

Conversation history needs to evolve toward a more typical agent-memory architecture:

- store structured conversation parts in a database first
- write markdown transcripts second as a user-facing artifact

Recommendation:

- design `memory_ops` against the DB-first model, not the current transcript-first shape
- preserve markdown transcripts as an inspectable artifact, but not as the primary storage/lookup substrate
- keep future vector-enhanced memory retrieval in mind when defining the tool contract

### 5. Tool Result Structuring for Authoring

The tool-first direction only stays pleasant if authored Python can branch on machine-readable results.

Current problem:

- `file_ops_safe` and `file_ops_unsafe` mostly return plain strings
- success, not-found, and error states share the same output channel
- Monty scripts end up branching on English text such as `"Cannot read"`

Recommendation:

- upgrade file tools to return machine-readable status and metadata alongside human-readable output
- prefer fixing this at the tool layer rather than teaching Monty helpers to parse prose
- ensure the `call_tool(...)` result surface preserves those structured fields cleanly

Initial target:

- `file_ops_safe`
- `file_ops_unsafe`

Initial desired fields:

- `status`
- `operation`
- `path` or `target`
- `exists` where applicable
- `error_type` where applicable

## Scope

### In Scope

- restructure `core/authoring` so helper definitions and implementations are easy to find
- clarify the target boundary between tools and Monty helpers
- reduce helper surface sprawl, even if that means removing existing experimental helpers
- improve authoring documentation to teach the chosen boundary
- tighten examples to reflect tool-first access patterns
- replace hidden context-template history inputs with a cleaner explicit approach
- design a `memory_ops` tool shape aligned with DB-first conversation storage
- redesign pending around an explicit helper surface that works with tool-derived file result sets
- preserve or improve observability in chat and workflow runs

### Out of Scope

- the full implementation of the DB-backed memory subsystem
- redesigning all workflows/templates at once
- rebuilding all tools as Monty-native helpers
- introducing a new frontmatter-bound object system right now

## Affected Areas

### Runtime / Contracts

- `/app/core/authoring/contracts.py`
- `/app/core/authoring/helper_catalog.py`
- `/app/core/authoring/helpers/` (new target layout)
- `/app/core/authoring/runtime/host.py`
- `/app/core/authoring/runtime/monty_runner.py`
- `/app/core/tools/code_execution_local.py`
- future `memory_ops` and pending helper/tool contract files

### Context Template Execution

- `/app/core/context/manager.py`
- `/app/core/context/templates.py`
- `/app/system/ContextTemplates/default.md`
- `/app/system/ContextTemplates/assistantmd_helper.md`

### Docs

- `/app/docs/tools/code_execution_local.md`
- `/app/docs/use/workflow_authoring.md`
- a future `memory_ops` doc
- pending helper docs
- possibly a new context-template-specific Monty doc if needed

### Validation

- `/app/validation/scenarios/integration/core/code_execution_local.py`
- `/app/validation/scenarios/integration/core/authoring_contract.py`
- `/app/validation/scenarios/integration/core/authoring_context_assembly.py`
- targeted chat/context-template scenarios as needed

## Validation Targets

### Existing Scenario Targets

- `integration/core/code_execution_local`
  - verify the intended helper surface still works
  - verify docs/examples align with actual runtime behavior

- `integration/core/authoring_contract`
  - verify the canonical Monty helper contract remains sound

- `integration/core/authoring_context_assembly`
  - verify context-template-specific authoring behavior remains explicit and correct

### Additional Validation To Add

- one scenario or assertion that demonstrates tool-first access from Monty:
  - file discovery via `call_tool(file_ops_safe, ...)`
  - then helper use only for orchestration/business logic

- one scenario or assertion that verifies explicit pending filtering/completion:
  - derive pending items from a file result set
  - complete only a selected subset
  - non-selected items still appear in the next run

- one scenario or assertion for `memory_ops`:
  - retrieve conversation state in chat
  - retrieve the same state inside a Monty script
  - verify the tool returns structured data aligned with future DB-first storage

## Migration Strategy

### Phase 0. Structural Cleanup

Status: complete

Completed:

- Created `core/authoring/helpers/` with one file per helper, similar to `core/tools` and `core/directives`
- Moved helper-specific contracts and execution logic out of the old monolithic registry file
- Replaced `builtins.py` with `helper_catalog.py` as the default helper-catalog entrypoint
- Reduced `runtime/host.py` to shared runtime state plus reserved Monty globals
- Kept shared helper-independent types in `contracts.py`
- Kept the registry generic; helper-specific registration now lives alongside each helper

Target shape:

- `core/authoring/helpers/retrieve.py`
- `core/authoring/helpers/complete_pending.py`
- `core/authoring/helpers/generate.py`
- `core/authoring/helpers/assemble_context.py`
- `core/authoring/helpers/parse_markdown.py`
- `core/authoring/helpers/finish.py`
- plus a small package-level registration surface and `helper_catalog.py`

### Phase 1. Freeze Boundary Drift

- Stop adding new access/query semantics to `retrieve(...)`
- Stop using frontmatter/input-binding proposals as implementation direction for now
- Keep pending explicit and host-owned

Status: in progress

Completed in this direction:

- Removed Monty `retrieve(...)` and `output(...)` from the helper surface
- Added `memory_ops` as the new source-agnostic history access tool
- Replaced `complete_pending(...)` with `pending_files(...)` using explicit `get` / `complete` operations

### Phase 2. Shift Guidance

- Update Monty docs and examples so file and external access are shown through tools first
- Keep helpers focused on orchestration and host-owned semantics
- Remove docs for helper paths that no longer fit the design
- Replace context-template-specific hidden runtime inputs with explicit tool-based history access

### Phase 3. Add Validation Coverage

- Add a scenario proving the intended tool/helper split in real Monty execution
- Add a scenario for explicit pending filtering/completion with partial batches
- Add a scenario for `memory_ops` in both chat and Monty contexts

### Phase 4. Remove Experimental Mismatches

- Remove helper-based file access that no longer fits the boundary
- Introduce the new pending helper shape
- Introduce `memory_ops` with a contract aligned to DB-first conversation storage
- Migrate experimental workflows/templates in this branch to the new model without compatibility shims

Status: in progress

## Risks

- Over-correcting and making Monty too verbose for common authoring tasks
- Under-correcting and continuing helper-surface sprawl
- Context-template history access remaining magical and confusing to an authoring LLM
- Losing observability if more behaviors are hidden behind generic local-code execution
- Designing `memory_ops` around current transcript files and blocking a stronger DB-first memory model later

## Assumptions

- The product remains committed to agent-authored workflows and context templates
- Tool observability is important enough to keep direct tools first-class
- Pending processing remains a real product need for scheduled workflows
- Full frontmatter-bound input objects are not justified as a primary design direction
- Experimental branch workflows/templates can be migrated directly without compatibility layers

## Next Phase

Feature Development

### Next Concrete Steps

1. Design the `memory_ops` tool contract around DB-first conversation storage and dual chat/Monty use.
2. Redesign pending as an explicit helper surface over tool-derived file result sets.
3. Remove helper-based file access that does not fit the target boundary.
4. Update docs, examples, and validation to teach and enforce the tool-first model.
