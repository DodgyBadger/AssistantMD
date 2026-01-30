# Release Notes


## 2026-01-30

This release introduces the **Context Manager** as a first-class feature, adds buffer-backed context passing, and then refines the directive model with a deliberate breaking change to improve semantics and future extensibility.

### Context manager (new feature)
- **Purpose**: curate a compact, task-relevant working context instead of appending full chat history, improving stability for long-running sessions.
- **Architecture**:
  - Template-driven: templates live in `AssistantMD/ContextTemplates/` (vault) or `system/ContextTemplates/` (global), with vault → system resolution.
  - Step-based: each `##` section (non-instructions) is a step that can include directives; steps run in order and inject system summaries.
  - Controlled history: `@recent-runs`, `@recent-summaries`, `passthrough_runs`, and `token_threshold` gate how much history is passed through or summarized.
  - Caching: optional `@cache` directive supports session/daily/weekly/duration reuse; cache is keyed by template + section and invalidated on template changes.
  - Observability: managed summaries are persisted to SQLite with template metadata and validation events capture key decisions.

### Buffers (virtualized I/O)
- Added a run-scoped buffer store to pass context between steps without file I/O.
- `@output variable: NAME` writes to a buffer; `@input variable: NAME` reads from it.
- Extended to workflows so the same buffer semantics work outside the context manager.
- Validation coverage added for buffer read/write/append/replace and required-missing behavior.

### Breaking changes
- **Directive rename**: `@input-file` → `@input`, `@output-file` → `@output` (no backward compatibility).
- **Scheme-based targets**: `@input` / `@output` now require explicit targets (`file: ` / `variable: `).
- **Parameter rename**: `paths-only` → `refs-only` for `@input` (no backward compatibility).

### Documentation
- Documentation updated to reflect the new directive names and scheme-based targets.
- Docs folder now includes a library of example context and workflow templates.


## 2026-01-24

This release refactors the UnifiedLogger and parts of the validation framework.

### UnifiedLogger
- Refactored logging to a sink-based model
- Added one-shot sink overrides in the form `logger.add_sink().info()` / `logger.set_sinks().warning()`
- Added new validation sink that logs to yaml files only during validation runs.
- Removed redundant trace decorator

### Validation framework
- Updated all integration scenarios to use the new validation sink logs to test internal state and removed tightly coupled helpers
- Removed all custom assertion helpers and refactored scenarios to use regular python assert statements
- Improved coverage of several integration scenarios
- Tools now emit tool_invoked validation events
- Overall reduction in surface area of the validation framework, slowly moving it toward a generic validation platform

## Other
- App runtime now assigns unique boot_id on each restart
- Review and cleanup of activity.log calls: dedupe, reduce noise and identify logging gaps
- Removal of lingering code from various deprecated features (e.g. chat compact endpoint, workflow creation endpoint, session type switching)
- Tools were normalized to pydantic_ai.tools.Tool
- Docs updated to reflect changes to logging and validation


## 2025-12-08

### Feature: Import to markdown pipeline
- Import PDF using pymupdf and optional Mistral OCR (with API key)
- Import URLs
- Ingestion settings and UI controls
- URL import accessible via LLM tool call
- Validation scenario for coverage
- **Note**: The importer is a work in progress and likely to change.

### Feature: Repair settings.yaml
- Warning in the UI if settings are missing from system/settings.yaml and provide repair tool
- Existing setting are unchanged
- Settings.yaml is backed up to system/setting.bak before repair

### Refactor 
- Consolidated redundant metadata APIs
- Hardened runtime path helpers, now require bootstrap/runtime context (no env fallbacks), entrypoints seed bootstrap roots early, secrets store uses a single authoritative path, and validation harness aligns with the same bootstrap rules.
- Logger/bootstrap safety: logfire configuration now defers when settings/secrets aren’t available during early imports to avoid startup crashes.
- Update docs

### Breaking change
- Custom scripts/entrypoints must call `set_bootstrap_roots` (or start a runtime context) before importing modules that resolve paths/settings; secrets overlay merging was removed in favor of a single `SECRETS_PATH` or `system_root/secrets.yaml`.


## 2025-11-29

- Runtime path resilience: renamed system root env/fields to `CONTAINER_SYSTEM_ROOT`/`system_root`, added `core/runtime/paths.py` helpers, and routed settings/secrets/logger/DB/workflow loaders through runtime-aware path resolution.
- Validation secrets handling: validation now uses the real secrets file via path helpers (no per-run copies), and removed teardown unlink to avoid deleting secrets. Devcontainer env updated to set `CONTAINER_SYSTEM_ROOT` alongside `CONTAINER_DATA_ROOT`.
- Doc update: architecture quick reference now lists the new path helper module.
- `.gitignore` now ignores the entire `system/` directory to keep runtime artifacts out of git.
- **Breaking change (env overrides):** If you previously set `SYSTEM_DATA_ROOT` to override the system path, update to `CONTAINER_SYSTEM_ROOT`. The default paths (`/app/data`, `/app/system`) are unchanged. Any custom devcontainer/env settings should switch to the new names.
