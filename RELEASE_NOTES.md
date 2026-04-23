# Release Notes

## 2026-04-22 - v0.6.0

### BREAKING: Markdown DSL replaced by Python authoring runtime

⚠️WARNING: This release replaces the markdown step-based authoring surface entirely with a Python-based authoring environment built on the **Pydantic Monty sandbox**. This affects every workflow and context template in your vault — all existing `.md` templates written using ## Step headings and @directives are now obsolete and must be migrated to the new format.

**Rationale**  
The old authoring approach relied on a custom language which was becoming increasingly complex for both humans and LLMs to understand. Attempts to teach the chat agent to write automations for you were failing. Rather than invent a new language, this release leans into what LLMs already know how to do well - write code. Now you can describe the research / knowledge automation you want and the chat agent will create it for you.

**Safety**  
This is not free-form Python. Authoring scripts run inside the Monty sandbox — a Python interpreter written in Rust with its own bytecode VM. Monty's default is zero access: no filesystem, no network, no environment variables, no arbitrary imports. The only way a script can interact with the outside world is through host helpers that AssistantMD explicitly registers — `generate()`, `call_tool()`, and so on. Each integration point is deliberate and auditable. The chat agent can write and run automation code on your behalf without any risk of it reaching outside the boundaries AssistantMD sets.

- **Workflows and context templates are now Python blocks.** Both live in a single `AssistantMD/Authoring/` folder — no more separate `Workflows/` and `ContextTemplates/` directories. Once you've migrated, you can delete the old folders.
- **Host helpers replace directives.** The Python sandbox exposes a concise set of host-owned functions — `generate()`, `assemble_context()`, `pending_files()`, `parse_markdown()`, `finish()`, `date`, and others — giving you real control flow, conditionals, and loops instead of declarative DSL syntax.
- **`Skills/` is now a canonical vault folder.** Drop plain-text skill files there and the default context template picks them up automatically, making them available to the chat agent without any template changes.
- **`soul.md` for simple customization.** Create `AssistantMD/soul.md` with plain instructions — agent personality, response style, ground rules — and the default template loads it as the system instruction. No template authoring needed for simple cases.
- **The chat agent can author and iterate templates for you.** Describe what you want; the agent drafts the file, places it in `Authoring/`, and can compile and refine it with you. The documentation has been significantly simplified and reorganized so the agent can find what it needs without manual pointers.

### Pydantic AI capabilities refactor

AssistantMD's tools and hooks have been restructured to align with the architectural direction Pydantic AI is taking around **capabilities** as the primary extension point for reusable agent behaviour.

- A new `core/llm/capabilities/` package owns AssistantMD-specific capability implementations.
- Chat and authoring agent construction now assembles capabilities explicitly rather than threading tool lists and history processors through ad-hoc arguments.

### Chat session persistence and management

Chat sessions are now persisted in SQLite and survive app restarts.

- A **session picker** in the chat settings panel lists all stored sessions for the active vault; selecting one rehydrates the full conversation view.
- Session titles are editable inline in the picker and appear in exported transcript filenames.
- **Transcript export is now on-demand**: click the export action in the session picker. Transcripts contain only user and assistant turns; tool calls and returns remain in the database.
- Exported transcript files are preserved when a session is deleted.
- **Bulk session purge** is available under Configuration > Misc with vault and age-threshold selectors.

### Unified thinking controls

- A single thinking control surface now covers both chat and the authoring runner.
- Set per-run thinking level in the chat UI and default thinking level in Application Settings.


### Tool changes

- All tools are now enabled by default (except `web_search_duckduckgo).
- `file_ops_safe` interface changes:
  - `target` parameter renamed to `path`.
  - `scope` renamed to `search_term` (search semantics flipped: `path` is now the directory boundary).
  - New `frontmatter` operation (returns selected frontmatter keys).
  - New `head` operation (returns the first N lines of a file).
- Local db-backed cache is now used for oversized tool results that exceed context limits, replacing the former buffer.
- Manual cache purge controls added to Configuration.


### Other improvements and fixes

- Scheduler startup hardened against stale job-store references: if serialized jobs point to modules that no longer exist (e.g. after a package rename), the store is wiped and the scheduler retries clean. Jobs are always re-added from current workflow files on the same boot.
- Prerelease tags (e.g. `v0.6-beta`) no longer move the `latest` Docker image tag; `latest` is only updated by stable `vX.Y.Z` releases.
- Fixed LaTeX false-positive on currency values: `$10` no longer triggers inline math detection.
- Tweaked the chat context template fallback chain.
- Validation event filenames padded to 5 digits for correct sort order past 99 events.
- Integration test suite updated throughout to match the new authoring contracts.


## 2026-03-31 - v0.5.0.

### BREAKING CHANGE: new selector/filter structure for the `@input` directive 
- The new mental model is: glob/file patterns select the candidate file set, `pending` or `latest` can filter that set, `order` sorts it, and `limit` is applied last. This allows greater flexibility. For example, previously, there was no way to fetch pending files in alphanumeric order - now there is.
- If your templates currently use substitution patterns `{pending}` or `{latest}`, you must update them.
- Old style:
  - `@input file: tasks/{pending:5}`
  - `@input file: journal/{latest:3}`
  - `@input file: projects/{latest}/notes.md`
- New style:
  - `@input file: tasks/* (pending, order=alphanum, dir=desc, limit=5)`
  - `@input file: journal/* (latest, limit=3)`
  - `@input file: projects/*/notes.md (latest, order=ctime, limit=1)`
  - `@input file: inbox/*.md (order=mtime, dir=desc, limit=10)`

### Added enable / disable operation to `workflow_run` tool
- You can now manage workflow state through the `workflow_run` tool with:
  - `enable_workflow`
  - `disable_workflow`
- Your workflows can include a step that disables the workflow when a condition is met so they don't run forever. Chat can also enable/disable workflows.
- **BREAKING CHANGE**: Previously, `enabled=true` was optional. If a schedule was present and `enabled` was missing, it would default `true`. New workflows now default to `enabled: false` if missing. If you create or copy in a workflow and expect it to start running on its schedule immediately, you will need to enable it explicitly.

### New tool: `browser`
- Added a Playwright-backed `browser` tool for extraction from known URLs when simple web extraction fails or pages depend on JavaScript.
- Intended usage order is: search first, `tavily_extract` second, `browser` as the heavier fallback.
- Browser policy is intentionally narrow:
  - downloads blocked
  - local/private network blocked, including redirects and subrequests
  - only read-oriented requests (`GET`/`HEAD`)
  - stateless per call
- Added browser-specific settings:
  - `browser_navigation_timeout_seconds`
  - `browser_selector_timeout_seconds`

### Other improvements
- Strengthened prompt-injection guidance for web tools so suspicious web content is treated as untrusted data and attacker strings are less likely to be echoed back verbatim.
- Chat now surfaces known model capability mismatches, such as attaching images to a non-vision model, as explicit client errors with actionable guidance instead of generic network/internal failures.
- Hardened chat session error handling, especially for streaming execution, so unexpected failures now leave structured `activity.log` diagnostics with session context, execution phase, exception type, and traceback information.
- Simplified the Workflows dashboard by making the main sections collapsible and unifying scheduled and unscheduled workflows into one clearer table with status and next-run information.
- Refreshed frontend/build dependencies to address npm vulnerability warnings, switched setup to `npm ci` for lockfile-based installs, and added dependency audit checks in CI.
- Documentation updates

## 2026-03-27 - v0.4.3.

### Added images as first-class input type
- Images are supported in chat, workflow and context templates. E.g. `@input file: myimage.png`
- `file_ops_safe(read)` supports image reads and markdown files that contain embedded images.
- Markdown files with embedded images are read in source-order so the LLM sees content as it appears in the document (text and images are interleaved into a multimodal prompt).
- When images cannot be attached (for example due to model or size limits), AssistantMD falls back gracefully with clear, followable image references instead of failing.
- Added image attachment size controls in settings: `chunking_max_image_mb_per_image`, `chunking_max_image_mb_total`, `chunking_max_images_per_prompt`.
- For markdown files with embedded images, AssistantMD preflights raw text token size first; if text alone exceeds `auto_buffer_max_tokens`, it skips multimodal attachment, returns text with normalized image reference markers and standard auto-buffer routing can apply.
- PDF import includes a page-image mode that outputs each page as an image, useful for documents where standard markdown conversion fails to output useful information.
- Import supports image-source OCR flows, including optional capture of OCR image assets in import outputs.

### Bug fixes
- Fixed inconsistent `@model none` handling across context and workflow execution. Steps/sections configured to skip now reliably bypass LLM execution instead of partially entering model setup paths.
- Fixed invalid model configuration handling so chat/default-model execution cannot proceed with skip-mode aliases like `none`; the app now raises a clear configuration error.
- Fixed directive date/time format token replacement so expanded values are not mutated by overlapping tokens (for example weekday/month text no longer gets corrupted by single-letter token passes).
- Fixed validation artifact consistency so scenario `timeline.md` outcomes now align with CLI pass/fail results (including explicit final outcome markers and teardown on failure paths). (Issue #28)

### Validation Scenario Refactor
- Reorganized integration validation into three lanes: root `integration/` for golden-path journeys, `integration/core` for deterministic contracts, and `integration/live` for live smoke scenarios.
- Consolidated overlapping contract coverage into core scenarios (especially `primitives_contract`) and retired redundant overlap cases.

### Documentation Updates
- Split contributor/agent guidance into progressive-disclosure docs under `docs/agent-guides/`, with a simplified root `AGENTS.md`.
- Added a running refactor checklist in `validation_suite_refactor_plan.md` and aligned validation documentation to the new scenario structure.


## 2026-02-25 - v0.4.2.

### Bug fix: OpenAI-compatible provider auth and base URL wiring
- Fixed OpenAI-compatible provider setup to consistently pass configured `api_key` and `base_url` values (from secrets or literal settings).
- Unified OpenAI-compatible routing to use `OpenAIProvider` so both authenticated remote endpoints and local no-auth endpoints work through the same path.
- Added custom `base_url` support for the `openai` provider configuration path.
- Fixed chat streaming assembly to include only visible text parts, preventing reasoning/thinking part prefixes (for example stray leading words like `"The"` in some provider streams).
- Allowed base-url-only OpenAI-compatible providers (for example local LM Studio without API key), so local endpoints are usable when `base_url` is configured.
- Updated configuration health warning logic to only warn when no LLM provider/model is usable, instead of warning whenever no API key exists.


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
