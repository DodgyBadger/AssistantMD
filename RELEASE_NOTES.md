# Release Notes

## 2026-02-24 - v0.4.1.

### Feature: LaTeX rendering in chat
This release adds first-class LaTeX rendering in assistant responses using bundled MathJax in the chat UI.

- Supports inline math (`$...$`, `\(...\)`) and display math (`$$...$$`, `\[...\]`).
- Preserves math while markdown is parsed, then typesets math after render (including streaming responses).
- Skips math parsing inside code blocks/inline code so examples stay literal.

### Security and rendering hardening
- Added DOMPurify to sanitize assistant-rendered HTML before inserting into the chat UI.
- Improved post-processing flow for assistant messages so link behavior, math rendering, and code-copy buttons are applied consistently.

### Chat instruction stack simplification
- Removed request-level custom chat instructions override from the chat API path.
- Consolidated default chat behavior into the regular instruction template/constants for more predictable prompting.

### Documentation and legal
- Added `THIRD_PARTY_NOTICES.md` with bundled frontend asset notices and dependency inventory references.
- Updated README links for reference docs, license, and third-party notices.

## 2026-02-20 - v0.4.0.

### Feature: Context manager
This release introduces the **Context Manager** which allows you to shape what the chat agent sees, from simple system‑prompt injection to multi‑step context assembly. It applies the lessons learned by research on long‑running agents: curated working sets, structured summaries and explicit attention budgeting beat dumping full transcripts into ever‑larger contexts.

It is template‑driven and step‑based, with explicit controls for how history is curated and optional caching/observability; see the docs for full details on directives, gating and persistence.

### Feature: Buffer (virtualized I/O)
The buffer is an in-memory key-value store that the chat UI, context templates and workflows can use to temporarily store data. Entries in the buffer are called variables. The buffer is useful for passing data between steps in a context or workflow template, or to avoid blowing up the context window with huge tool outputs.

A new `buffer_ops` tool allows the LLM to access buffer variables systematically. This feature is the first step toward enabling a robust [RLM-style approach](https://alexzhang13.github.io/blog/2025/rlm/) to context management.

### Additional features
- Added `@input (...properties...)` mode to inject frontmatter properties instead of full file content.
- Added formatted time patterns for directives.
- Added `workflow_run` tool support in chat to list and execute workflows from the active vault.

### Breaking changes
- **Directive rename**: `@input-file` → `@input`, `@output-file` → `@output` (no backward compatibility).
- **Scheme-based targets**: `@input` / `@output` now require explicit targets (`file: ` / `variable: `).
- **Parameter rename**: `paths-only` → `refs-only` for `@input` (no backward compatibility).
- **Tool deprecation**: Removed `import_url` and `documentation_access` tools (assisted template creation is now handled using the context manager).

### Documentation
- Significant documentation updates.
- New library of example context and workflow templates.
- LLM can read documentation with file_ops_safe using virtual path root `__virtual_docs__/`.

### Chores
- Upgraded `pydantic-ai` to `1.60.0` and refreshed the lockfile.
- Hardened release workflow trigger logic and removed changelog dependency from CI release flow.
- Enforced lint/tooling hygiene and cleanup across context/template execution paths.

### Bugs / Fixes
- Chat UI now preserves selected vault/model/template/tools across metadata refreshes.
- Vault selector is locked to the active chat session to prevent mid-session vault switches, with clearer tooltip guidance.
- Assistant message links now open in a new tab to avoid disrupting current session.
- Hardened `file_ops_safe` search: configurable timeout, case-insensitive matching, safer scope boundary checks, and normalized result paths.
- Hardened vault path validation against symlink-based escape paths.
- Improved template-facing error surfacing in context manager/workflow execution.
- Standardized quoted-comma directive parameter handling to reduce parsing edge-case failures.


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
