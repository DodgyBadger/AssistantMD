# DSL Removal & Unified Authoring Surface — Refactor Plan

**Branch:** `feature/workflow_python_sdk`  
**Goal:** Remove the DSL execution surface entirely, unify authoring and context templates under a single `AssistantMD/Authoring/` directory, and simplify the execution model so that all user-authored logic runs as Monty (Python) workflows discriminated by `run_type` frontmatter.

---

## Background

The codebase currently maintains two distinct authoring surfaces:

| Surface | Directory | Engine | Frontmatter |
|---|---|---|---|
| Workflow | `AssistantMD/Workflows/` | Monty or DSL (`workflow_engine`) | Required |
| Context Template | `AssistantMD/ContextTemplates/` | DSL or Monty (`workflow_engine: monty`) | Optional |

The DSL surface (`core/directives/`, `core/workflow/`, `workflow_engines/step/`) is an older, lower-capability execution model. All new authoring uses the Monty engine. The `core/context/manager.py` already contains a full Monty execution path alongside its DSL path, gated by `_is_authoring_context_template()`.

The vision is:

- One directory: `AssistantMD/Authoring/`
- One engine: Monty Python blocks
- One discriminator: `run_type: workflow | context` in frontmatter
- No directive processors, no `@directive-name` syntax in template files, no step-based execution

---

## What Survives

Before deleting anything, several utilities extracted from `core/directives/` are used by non-DSL code and must be preserved:

| Symbol | Currently in | Used by | Action |
|---|---|---|---|
| `DirectiveValueParser` | `core/directives/parser.py` | `tool_binding.py`, `output_resolution.py`, `model_selection.py` | Extract to `core/utils/value_parser.py` |
| `ModelDirective.process_value` logic | `core/directives/model.py` | `core/chat/executor.py`, `core/llm/agents.py` | Inline into `core/llm/model_selection.py` as `resolve_model_alias()` |
| `ToolsDirective.process_value` logic | `core/directives/tools.py` | `core/chat/executor.py`, `core/context/manager_helpers.py` | Replace with direct calls to `resolve_tool_binding()` already in `tool_binding.py` |
| `WriteModeDirective.process_value` logic | `core/directives/write_mode.py` | `core/authoring/shared/output_resolution.py` | Inline the 3-line validation into `normalize_write_mode()` |

The `core/workflow/parser.py` shim is already cleaned up: `parse_markdown_sections` is now in `core/utils/markdown.py` and `parse_simple_frontmatter` is in `core/utils/frontmatter.py`. The `core/authoring/service.py` no longer imports `validate_config` from the DSL layer.

---

## Phases

### ✅ Phase 1 — Extract Surviving Directive Utilities

**Goal:** Break `DirectiveValueParser`, `ModelDirective`, and `ToolsDirective` out of `core/directives/` so the DSL package can be deleted later without breaking non-DSL callers.

#### ✅ 1a. Create `core/utils/value_parser.py`

Move `DirectiveValueParser` verbatim from `core/directives/parser.py` into a new standalone module:

```
core/utils/value_parser.py
```

- Copy the class exactly; it has no imports from `core/directives/`.
- Update the three callers:
  - `core/authoring/shared/tool_binding.py`: `from core.directives.parser import DirectiveValueParser` → `from core.utils.value_parser import DirectiveValueParser`
  - `core/authoring/shared/output_resolution.py`: same swap
  - `core/llm/model_selection.py`: same swap
- Leave a re-export shim in `core/directives/parser.py` for now:  
  `from core.utils.value_parser import DirectiveValueParser  # noqa: F401`  
  (Remove when `core/directives/` is deleted in Phase 4.)
- The old class body in `parser.py` was deleted; the file now only imports and re-exports from `value_parser`.

#### ✅ 1b. ~~Inline `ModelDirective` into `core/llm/model_selection.py`~~ → Extracted to `core/llm/model_factory.py`

> **Deviation from plan:** `ModelDirective.process_value()` is not a thin wrapper — it contains 100+ lines of provider-specific Pydantic AI model instantiation logic (Anthropic, Google, OpenAI, Grok, Mistral, custom endpoints). This logic does not belong in `model_selection.py` (which is a spec-only module). Instead, a new dedicated module `core/llm/model_factory.py` was created with a public `build_model_instance(value)` function.
>
> `ModelDirective.process_value()` now delegates to `build_model_instance()` — the class is retained as a thin shim for DSL compatibility until Phase 4.

- `core/chat/executor.py`: Removed `ModelDirective` import; calls `build_model_instance(model)` directly
- `core/llm/agents.py`: Same swap
- `core/context/manager.py`: Same swap (addressed in Phase 2 — `manage_context` was removed entirely)

#### ✅ 1c. Replace `ToolsDirective` with direct `resolve_tool_binding` calls

- `core/chat/executor.py`: calls `resolve_tool_binding()` directly; uses `binding.tool_functions` / `binding.tool_instructions`
- `core/context/manager_helpers.py`: calls `resolve_tool_binding()` per value + `merge_tool_bindings()` (both already existed in `tool_binding.py`)
- Note: `resolve_section_tools()` in `manager_helpers.py` was also updated here, then deleted entirely in Phase 2 when the DSL path was removed.

#### ✅ 1d. Inline `WriteModeDirective` into `output_resolution.py`

`normalize_write_mode()` now contains the 5-line inline validation with `_VALID_WRITE_MODES` frozenset. `WriteModeDirective` import removed.

**Verification:** All 10 touched files passed `python -m py_compile`. Zero remaining `from core.directives` imports in non-DSL callers.

---

### ✅ Phase 2 — Remove DSL Execution Path from Context Manager

**Goal:** The `core/context/manager.py` branches between a DSL path and a Monty path. Remove the DSL branch entirely.

#### ✅ 2a. Remove the branch point and DSL processor

- Deleted `_is_authoring_context_template()` — the gating function is gone.
- Deleted the entire `manage_context()` function (~120 lines) — it was only ever called from `run_context_section()` in the DSL path. No external callers existed.
- `build_context_manager_history_processor()` simplified: removed `ensure_builtin_directives_registered()`, `get_global_registry()`, `SectionExecutionContext` construction, and the entire DSL `processor` closure (~230 lines). Now unconditionally calls `parse_authoring_template_text()` and returns the Monty processor.
- Removed `manager_runs` parameter from `build_context_manager_history_processor()` (was only passed to `SectionExecutionContext`).
- Fixed two `metadata=` → `data=` logger bugs found during the audit (`_build_authoring_context_history` and the template-load warning).

#### ✅ 2b. Clean up `manager_helpers.py`

- Removed `_raise_context_template_error()` — only called from DSL functions.
- Removed `format_input_files_for_prompt()`, `has_empty_input_file_directive()`, `hash_output()` — DSL-path helpers with no surviving callers.
- Removed 10 DSL-only functions that processed `@directive` values via the registry: `resolve_section_int`, `resolve_section_header`, `resolve_section_write_mode`, `resolve_section_outputs`, `resolve_section_cache_config`, `resolve_section_tools`, `resolve_section_inputs`, `resolve_cache_decision`, `route_section_outputs`, `run_context_section` (~950 lines total).
- Inlined `_parse_passthrough_runs` from `core/directives/context_manager.py` into `resolve_passthrough_runs()` — removes the last `core.directives` import from `manager_helpers.py`.
- Removed 9 now-unused imports (cache store functions, `BufferStore`, `model_utils`, `routing`, `chunking`, `ResolvedOutputTarget`, `cache_semantics`, `tool_binding`).

> **Note:** `run_slice` and `extract_role_and_text` were kept — confirmed they are imported by `core/memory/providers.py` and `core/authoring/helpers/runtime_common.py`.

**Verification:** Both `manager.py` and `manager_helpers.py` pass `python -m py_compile`. Zero `from core.directives` imports remain in any non-DSL file.

---

### ✅ Phase 3 — Introduce `run_type` Frontmatter and Unified Directory

**Goal:** Introduce the `run_type` frontmatter key and unify the file-system layout. This is the user-visible part of the migration.

#### ✅ 3a. Add `AUTHORING_DIR` constant

In `core/constants.py`, add:

```python
AUTHORING_DIR = "Authoring"  # Unified authoring directory (replaces Workflows + ContextTemplates)
```

Keep `WORKFLOW_DEFINITIONS_DIR` and `CONTEXT_TEMPLATE_DIR` as deprecated aliases pointing to the old paths until all loaders are updated.

#### ✅ 3b. Update workflow loader to support `run_type`

In `core/workflow/loader.py` (or wherever workflows are discovered), update the discovery logic to:
1. Look for files under `AssistantMD/Authoring/` in addition to `AssistantMD/Workflows/`
2. Treat a file as a "workflow" when `run_type: workflow` (or `run_type` absent and `schedule` is set)
3. Treat a file as a "context template" when `run_type: context`

The frontmatter spec:
```yaml
run_type: workflow   # executed on schedule / manual trigger
run_type: context    # executed during history_processor context pass
```

#### ✅ 3c. Update context template loader

In `core/context/templates.py`, update `load_template()` and `list_templates()` to:
1. Look under `AssistantMD/Authoring/` in addition to `AssistantMD/ContextTemplates/`
2. Filter by `run_type: context` when the new directory is used

#### ✅ 3d. Update `WorkflowConfigSchema` / authoring service

In `core/authoring/service.py`, extend `_validate_monty_frontmatter()` to validate `run_type` when present:
```python
VALID_RUN_TYPES = frozenset({"workflow", "context"})
run_type = str(frontmatter.get("run_type") or "").strip().lower()
if run_type and run_type not in VALID_RUN_TYPES:
    raise ValueError(f"Invalid run_type '{run_type}'. Must be one of: {', '.join(sorted(VALID_RUN_TYPES))}")
```

#### ✅ 3e. Compile-check endpoint update

The `compile_candidate_workflow` function in `service.py` should also validate `run_type` as part of compile-only checks.

**Verification:** All four touched files pass `python -m py_compile`. `run_type` filter confirmed in grep across all call sites.

---

### ✅ Phase 4 — Delete DSL Packages

**Goal:** Remove all DSL-only code. By this point, no surviving code imports from these modules.

#### Packages to delete entirely

| Package / file | Why safe to delete |
|---|---|
| `core/directives/` (entire package) | All consumers migrated in Phase 1–2; `DirectiveValueParser` moved to `core/utils/value_parser.py` |
| `core/workflow/` (entire package) | `parse_markdown_sections` already moved to `core/utils/markdown.py`; `parse_simple_frontmatter` already in `core/utils/frontmatter.py`; all remaining code is DSL-only |
| `workflow_engines/step/` (entire package) | DSL step execution engine; replaced entirely by `workflow_engines/monty/` |
| `workflow_engines/__init__.py` registry shim | If it only dispatches to `step/` and `monty/`; keep if `monty/` dispatch still needed |

#### Files to delete (selective)

- `core/directives/bootstrap.py` — registers all DSL directive processors; only called from `core/workflow/parser.py` step processing
- `core/directives/registry.py` — directive processor registry; no post-Phase-2 callers
- `core/directives/base.py` — `DirectiveProcessor` ABC; no post-Phase-2 concrete classes outside `core/directives/`
- `core/workflow/parser.py` — `WorkflowConfigSchema`, `process_step_content`, `ProcessedStep`; `parse_markdown_sections` already re-exported from `core/utils/markdown.py`

#### Files to shrink (keep residual utilities)

- `core/directives/parser.py` — Remove `parse_directives()`, `ParsedDirectives`, all directive-scanning logic. The file can be deleted entirely once `DirectiveValueParser` is moved (Phase 1a). The re-export shim added in Phase 1a is removed here.
- `core/context/templates.py` — Remove `parse_directives()` call in `_select_instruction_and_template_sections()`; remove `TemplateSection.directives` field and all directive-aware section logic. Templates no longer carry `@directive` syntax.

#### Verify no remaining imports

```bash
grep -r "from core.directives" --include="*.py" .
grep -r "from core.workflow" --include="*.py" .
grep -r "workflow_engines.step" --include="*.py" .
```

All results should be zero after this phase.

---

### Phase 5 — Migrate Existing Templates and Workflows

**Goal:** Convert all existing DSL-based files to Monty Python format with `run_type` frontmatter.

#### 5a. Inventory existing DSL templates

```bash
find . -path "*/AssistantMD/ContextTemplates/*.md" | xargs grep -l "workflow_engine"
find . -path "*/AssistantMD/ContextTemplates/*.md" | xargs grep -L "workflow_engine"  # pure-DSL files
```

Files without `workflow_engine: monty` are DSL templates. Categorize them:
- Files using `@directive` syntax only → trivial to migrate (strip directives, add Python block)
- Files with `@input` / `@output` / `@header` → need Python equivalents using existing Monty host methods

#### 5b. Migration pattern for DSL templates

A DSL context template like:

```markdown
---
workflow_engine: dsl
---
@input {today}
@output summaries/today.md

## Context Instructions
Summarize recent activity.
```

Becomes a Monty context template:

```markdown
---
run_type: context
workflow_engine: monty
---

```python
from datetime import date
inputs = [host.read_file(host.format_date(date.today()))]
host.set_output("summaries/today.md")
```

## Context Instructions
Summarize recent activity.
```

The Monty host API (`WorkflowAuthoringHost`) already exposes methods for reading files, formatting dates, setting output paths, and managing buffers — document the mapping as part of this migration.

#### 5c. Seed template updates

The `core/context/template_seed/` directory contains default templates seeded to `system/ContextTemplates/`. Update all seed templates to Monty format and move them to a new `core/context/template_seed/` path that seeds into `system/Authoring/`.

#### 5d. Move files on disk (optional — do last)

Once all loaders support both old and new paths (Phase 3), physically move files:
- `AssistantMD/Workflows/*.md` → `AssistantMD/Authoring/*.md` (add `run_type: workflow`)
- `AssistantMD/ContextTemplates/*.md` → `AssistantMD/Authoring/*.md` (add `run_type: context`)

The old directories can coexist during transition; remove them once empty.

---

### Phase 6 — Bootstrap and Runtime Cleanup

**Goal:** Remove DSL-related startup code, simplify `core_services.py`, and clean up constants.

#### 6a. Remove `ensure_builtin_directives_registered()`

This function (called from `core/workflow/parser.py:process_step_content()`) registers all DSL directive processors at startup. Once `process_step_content()` is deleted (Phase 4), this call is unreachable. Delete:
- The call site
- `core/directives/bootstrap.py`
- Any startup hook in `core_services.py` that calls it

#### 6b. Simplify `core_services.py`

Read `core_services.py` and remove any service registration or startup hooks that only exist to support DSL execution:
- Directive processor registration
- DSL registry initialization
- Step-execution engine setup

#### 6c. Remove deprecated directory constants

Once all loaders have been updated (Phase 3) and old directories are empty (Phase 5d), remove from `core/constants.py`:
```python
WORKFLOW_DEFINITIONS_DIR = "Workflows"   # → replaced by AUTHORING_DIR
CONTEXT_TEMPLATE_DIR = "ContextTemplates"  # → replaced by AUTHORING_DIR
```

Update all remaining references.

#### 6d. Rename `workflow_engines/monty/` (optional)

With `workflow_engines/step/` gone, the `workflow_engines/` container is a single-entry namespace. Consider moving `workflow_engines/monty/` to `core/authoring/engine/` and deleting the `workflow_engines/` top-level package. This is cosmetic but reduces namespace confusion.

---

### Phase 7 — Fold `core/context/` into `core/authoring/`

**Goal:** Eliminate `core/context/` as a separate package. Everything it contains is either an authoring concern (template loading, context management) or a shared cache utility that already serves `core/authoring/` code. Moving it completes the authoring surface consolidation started in Phases 1–4.

#### Current `core/context/` inventory

| File | What it does | External callers outside `core/context/` |
|---|---|---|
| `templates.py` | Context template discovery (`load_template`, `list_templates`, `seed_system_templates`, `TemplateRecord`, `TemplateSection`) | `core/chat/executor.py`, `core/runtime/bootstrap.py`, `core/context/manager.py` (internal) |
| `manager.py` | `build_context_manager_history_processor` — Monty history processor factory | `core/chat/executor.py` |
| `manager_helpers.py` | Template runtime prep, message utilities (`extract_role_and_text`, `run_slice`), frontmatter resolvers | `core/authoring/helpers/runtime_common.py`, `core/memory/providers.py` |
| `manager_types.py` | `ContextTemplateError` only | `core/context/manager.py` (internal) |
| `store.py` | SQLite-backed cache artifact store | `core/authoring/helpers/generate.py`, `core/authoring/helpers/read_cache.py`, `core/context/manager.py`, `api/services.py`, validation scenarios |
| `cache_semantics.py` | Cache TTL/mode parsing and validity checks | `core/context/store.py`, `core/authoring/helpers/generate.py` |
| `template_seed/` | Default context templates seeded to `system/ContextTemplates/` | `seed_system_templates()` at bootstrap |

#### 7a. Unify template discovery

`core/context/templates.py` is the context-template half of what `core/authoring/template_discovery.py` does for workflows. Long-term both should be a single layer that discovers all files under `AssistantMD/Authoring/` and routes by `run_type`. The clean path:

1. Move `TemplateRecord`, `TemplateSection`, `load_template`, `list_templates`, `_discover_template_files` into `core/authoring/template_discovery.py`, which becomes the single vault-scanning entry point for both `run_type: workflow` and `run_type: context` files.
2. Move `seed_system_templates` and `template_seed/` to `core/authoring/template_seed/` — update `bootstrap.py` import.
3. Delete `core/context/templates.py`.

Key consideration: the context template loader currently still supports legacy `AssistantMD/ContextTemplates/` paths for backward compatibility (Phase 3). That backward-compat logic moves with it.

#### 7b. Move context manager

`manager.py` + `manager_helpers.py` + `manager_types.py` become `core/authoring/context_manager.py` (or a `core/authoring/context_manager/` sub-package if the size warrants it).

- `build_context_manager_history_processor` is the only public API — its import path in `core/chat/executor.py` updates to `core.authoring.context_manager`.
- `extract_role_and_text` and `run_slice` are imported by `core/memory/providers.py` — these are general message-history utilities that don't belong in a context-manager module. Extract them to `core/utils/messages.py` before the move so external callers don't get a surprising import path.
- `ContextTemplateError` folds inline into the context manager module (it's a one-class file).

#### 7c. Move cache layer

`cache_semantics.py` and `store.py` move to `core/authoring/`:

- `core/authoring/cache_semantics.py` — no callers outside the authoring+context surface, straightforward move.
- `core/authoring/cache_store.py` — rename from `store.py` to avoid ambiguity with other store modules; update ~8 import sites across `generate.py`, `read_cache.py`, `manager.py`, `api/services.py`, and validation scenarios.

#### 7d. Delete `core/context/`

Once 7a–7c are complete, verify zero remaining imports from `core.context` and remove the package.

```bash
grep -r "from core\.context" --include="*.py" .  # must be empty
```

#### Sequencing and risks

| Risk | Mitigation |
|---|---|
| `extract_role_and_text` / `run_slice` used by `core/memory/` | Extract to `core/utils/messages.py` in step 7b *before* moving manager files; update both callers in the same commit |
| `TemplateRecord` / `TemplateSection` referenced in many type annotations | Do a grep-and-replace pass after moving; `py_compile` each touched file |
| `seed_system_templates` called at bootstrap | Update `core/runtime/bootstrap.py` import as part of 7a |
| Cache store DB path logic may have hidden coupling | Read `store.py` fully before moving; confirm `_get_db_path` only depends on `core.database` utilities, not `core.context` internals |
| `api/services.py` imports from `core.context` | API layer gets updated in 7c; no functional change, import-path only |

Phase 7 can begin as soon as Phase 6 is complete, but 7a (template discovery unification) depends on Phase 5 (legacy `ContextTemplates/` directory emptied), so it may be sequenced after 5d.

---

## Dependency Graph (phases must respect ordering)

```
Phase 1 (extract utilities)
  └─→ Phase 2 (remove DSL context path)
        └─→ Phase 4 (delete DSL packages)
              └─→ Phase 6 (bootstrap cleanup)
Phase 3 (run_type + unified dir) — can start in parallel with Phase 2
Phase 5 (migrate templates) — requires Phase 3 loader changes
  └─→ Phase 7a (unify template discovery) — requires Phase 5d (ContextTemplates/ emptied)
Phase 7b/7c/7d (fold core/context/) — requires Phase 4; 7b requires extract to core/utils/messages.py first
```

Phases 2 and 3 can be worked in parallel by different branches or sequentially in the same branch.

---

## Files Changed Summary

| Action | Files |
|---|---|
| **New** | `core/utils/value_parser.py` |
| **Modified** | `core/utils/markdown.py` (already done), `core/utils/frontmatter.py` (already done), `core/authoring/service.py` (already done), `core/authoring/shared/output_resolution.py`, `core/authoring/shared/tool_binding.py`, `core/llm/model_selection.py`, `core/chat/executor.py`, `core/llm/agents.py`, `core/context/manager.py`, `core/context/manager_helpers.py`, `core/context/templates.py`, `core/constants.py` |
| **Deleted** | `core/directives/` (entire), `core/workflow/` (entire), `workflow_engines/step/` (entire) |
| **Migrated** | All files in `AssistantMD/ContextTemplates/` and `AssistantMD/Workflows/` |

---

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| DSL templates in user vaults not yet migrated | Phase 3 loaders support both directories; old paths remain readable until Phase 5d |
| `ToolsDirective.merge_results()` accumulation logic lost | Extract merge logic to `tool_binding.merge_tool_bindings()` before deleting `core/directives/tools.py` |
| `compile_candidate_workflow` currently only validates `workflow_engine: monty` | Extend to accept `run_type: context` and `run_type: workflow` as valid inputs |
| Seed templates get seeded to wrong path post-Phase-3 | Update `seed_system_templates()` to target `system/Authoring/` concurrently with Phase 3 |
| `core_services.py` startup order dependencies | Audit call graph before removing bootstrap hooks; failing startup is non-obvious |

---

## Already Completed (this branch)

### Prior hardening pass (pre-plan)

- `core/utils/markdown.py` — `parse_markdown_sections` extracted from `core/workflow/parser.py`
- `core/context/templates.py` — updated to import from `core/utils/markdown`
- `core/workflow/parser.py` — delegates `parse_markdown_sections` to `core/utils/markdown`
- `core/authoring/service.py` — removed `validate_config` DSL import; added inline `_validate_monty_frontmatter`
- `core/authoring/shared/input_resolution.py` — `WorkflowInputResolver` class removed; module-level functions; `add_sink` fix
- `core/authoring/shared/output_resolution.py` — `route_tool_output` moved here from `tool_binding.py`; `clean_optional_string` made public; `add_sink` fix
- `core/authoring/shared/tool_binding.py` — `_route_tool_output` removed; `metadata=` → `data=` fix
- `core/utils/routing.py` — logger added; empty-dirname guard for `os.makedirs`
- `core/context/manager_helpers.py` — 8x `metadata=` → `data=` fix; 2x silent except fix

### Phase 1 (this session)

- `core/utils/value_parser.py` — new; `DirectiveValueParser` extracted from `core/directives/parser.py`
- `core/llm/model_factory.py` — new; `build_model_instance()` extracted from `ModelDirective.process_value()`
- `core/directives/parser.py` — class body removed; re-exports `DirectiveValueParser` from `core/utils/value_parser`
- `core/directives/model.py` — stripped to thin shim; `process_value()` delegates to `build_model_instance()`
- `core/authoring/shared/tool_binding.py` — import updated to `core.utils.value_parser`
- `core/authoring/shared/output_resolution.py` — import updated; `WriteModeDirective` replaced with inline validation
- `core/llm/model_selection.py` — import updated to `core.utils.value_parser`
- `core/chat/executor.py` — `ModelDirective` and `ToolsDirective` removed; uses `build_model_instance` and `resolve_tool_binding` directly
- `core/llm/agents.py` — `ModelDirective` removed; uses `build_model_instance` directly
- `core/context/manager_helpers.py` — `ToolsDirective` removed; uses `resolve_tool_binding` + `merge_tool_bindings` directly

### Phase 2 (this session)

- `core/context/manager.py` — `_is_authoring_context_template()` deleted; `manage_context()` deleted; `build_context_manager_history_processor()` simplified to Monty-only path; 6 DSL imports removed; 2 `metadata=` bugs fixed
- `core/context/manager_helpers.py` — 10 DSL-only functions deleted (~950 lines); `_parse_passthrough_runs` inlined; 9 DSL-only imports removed

### Phase 4 (this session)

**Pre-deletion caller fixes:**
- `core/authoring/helpers/generate.py` — replaced lazy `ModelDirective().process_value()` with `build_model_instance()`; import moved to module top
- `core/context/templates.py` — removed `from core.directives.parser import parse_directives`; rewrote `_select_instruction_and_template_sections()` to use content directly; removed `directives` field from `TemplateSection` and `TemplateRecord`
- `core/context/manager_helpers.py` — removed `template_directives` variable and `directives=` arg from `TemplateSection` construction
- `core/context/manager_types.py` — stripped to `ContextTemplateError` only; all DSL-only dataclasses removed (`SectionExecutionContext`, `CacheDecision`, `InputResolutionResult`, `OutputRoutingResult`, `SectionExecutionResult`, `ContextManagerInput`, `ContextManagerResult`, `ContextManagerDeps`, `ManageContextFn`)
- `core/workflow/loader.py` — removed `from .parser import parse_workflow_file, validate_config`; added inline `_parse_workflow_file()` and `_validate_workflow_config()` using `parse_simple_frontmatter`, `parse_markdown_sections`, `parse_schedule_syntax`; added `VALID_WEEK_DAYS` import
- `validation/core/system_controller.py` — removed `import workflow_engines.step.workflow as workflow_module`; removed step-engine datetime monkey-patching from `stop_system()` and `set_test_date()`
- `validation/core/workflow_execution_service.py` — removed `with patch('workflow_engines.step.workflow.datetime')` block; flattened nested context managers

**Deleted:**
- `core/directives/` — entire package (14 files)
- `core/core_services.py` — DSL convenience wrapper; only caller was `workflow_engines/step/workflow.py`
- `core/workflow/parser.py`, `execution_prep.py`, `tool_binding.py`, `input_resolution.py`, `output_resolution.py`, `python_steps/` — all DSL-only
- `workflow_engines/step/` — entire DSL step execution engine (2 files)

**Kept (`core/workflow/` package slimmed, not deleted):**
- `core/workflow/loader.py` — `WorkflowLoader`, `discover_vaults`, `discover_workflow_files` (used by runtime bootstrap and validation)
- `core/workflow/definition.py` — `WorkflowDefinition` dataclass (used by scheduler)
- `core/workflow/__init__.py` — updated docstring

> **Deviation from plan:** The plan called for deleting `core/workflow/` entirely, but `WorkflowLoader` and `WorkflowDefinition` are still needed by `core/runtime/bootstrap.py`, `core/runtime/context.py`, and the validation harness. The package was stripped to these two surviving modules; the DSL files within it were deleted.

**Verification:** All 13 compile checks pass. Zero `from core.directives` imports remain. Zero `workflow_engines.step` imports remain.

### Phase 3 (this session)

- `core/constants.py` — `AUTHORING_DIR = "Authoring"` added
- `core/workflow/loader.py` — `_scan_md_files_one_level()` extracted; `discover_workflow_files()` creates and scans `AssistantMD/Authoring/`; `load_workflows()` path check extended to allow `AUTHORING_DIR`; `run_type: context` files skipped
- `core/context/templates.py` — `load_template()` and `list_templates()` extended to look in `AssistantMD/Authoring/` (filter by `run_type: context`); `seed_system_templates()` creates `system/Authoring/` directory
- `core/authoring/service.py` — `_VALID_RUN_TYPES` constant added; `compile_candidate_workflow()` infers `monty` engine when `run_type` is set; `_validate_monty_frontmatter()` validates `run_type` when present
