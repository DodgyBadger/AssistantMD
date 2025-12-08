# Release Notes

## 2025-12-08

- Ingestion end-to-end: added PDF import pipeline with optional Mistral OCR, markitdown-based Office extraction, configurable import output base path, URL ingestion flow/tool, and UI controls plus a validation scenario for coverage.
- Unified metadata API and ingestion controls surfaced via the UI; ingestion worker interval is now configurable.
- Runtime hardening follow-up: path helpers now require bootstrap/runtime context (no env fallbacks), entrypoints seed bootstrap roots early, secrets store uses a single authoritative path, and validation harness aligns with the same bootstrap rules.
- Logger/bootstrap safety: logfire configuration now defers when settings/secrets aren’t available during early imports to avoid startup crashes.
- Docs updated (architecture/validation) and runtime-hardening plan captured for ongoing hardening work.
- **Breaking change:** Custom scripts/entrypoints must call `set_bootstrap_roots` (or start a runtime context) before importing modules that resolve paths/settings; secrets overlay merging was removed in favor of a single `SECRETS_PATH` or `system_root/secrets.yaml`.

## 2025-11-29

- Runtime path resilience: renamed system root env/fields to `CONTAINER_SYSTEM_ROOT`/`system_root`, added `core/runtime/paths.py` helpers, and routed settings/secrets/logger/DB/workflow loaders through runtime-aware path resolution.
- Validation secrets handling: validation now uses the real secrets file via path helpers (no per-run copies), and removed teardown unlink to avoid deleting secrets. Devcontainer env updated to set `CONTAINER_SYSTEM_ROOT` alongside `CONTAINER_DATA_ROOT`.
- Doc update: architecture quick reference now lists the new path helper module.
- `.gitignore` now ignores the entire `system/` directory to keep runtime artifacts out of git.
- **Breaking change (env overrides):** If you previously set `SYSTEM_DATA_ROOT` to override the system path, update to `CONTAINER_SYSTEM_ROOT`. The default paths (`/app/data`, `/app/system`) are unchanged. Any custom devcontainer/env settings should switch to the new names.
