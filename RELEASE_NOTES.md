# Release Notes

## 2025-11-29

- Runtime path resilience: renamed system root env/fields to `CONTAINER_SYSTEM_ROOT`/`system_root`, added `core/runtime/paths.py` helpers, and routed settings/secrets/logger/DB/workflow loaders through runtime-aware path resolution.
- Validation secrets handling: validation now uses the real secrets file via path helpers (no per-run copies), and removed teardown unlink to avoid deleting secrets. Devcontainer env updated to set `CONTAINER_SYSTEM_ROOT` alongside `CONTAINER_DATA_ROOT`.
- Doc update: architecture quick reference now lists the new path helper module.
- `.gitignore` now ignores the entire `system/` directory to keep runtime artifacts out of git.
- **Breaking change (env overrides):** If you previously set `SYSTEM_DATA_ROOT` to override the system path, update to `CONTAINER_SYSTEM_ROOT`. The default paths (`/app/data`, `/app/system`) are unchanged. Any custom devcontainer/env settings should switch to the new names.
