# Runtime Path/Secrets Hardening Plan

Goal: remove reliance on mutable env fallbacks for runtime paths/secrets and make the runtime context the single source of truth.

## Proposed Changes
- **Path helpers**: Update `get_data_root` / `get_system_root` to require an active runtime context and raise if absent (no env fallback after bootstrap).
- **Secrets store**: Require an explicit `SECRETS_PATH` or runtime context path; when set, treat it as authoritative (no implicit base merge).
- **Bootstrap order**: Ensure runtime context is established before any code that touches path/secrets helpers; keep env usage only for bootstrap compatibility if needed.
- **Validation runner**: Start the runtime context before invoking any helper that reads paths/secrets; drop per-run env mutations for paths.
- **Early callers audit**: Identify module-level or early init code (ingestion, settings validation, tests) that currently depends on env defaults and refactor to take paths from runtime/config instead.
- **Logger safety**: Decouple `UnifiedLogger` init from path helpers so it can start in a bootstrap-safe mode (console only) and switch to context paths after the runtime is set, avoiding crashes when path helpers stop allowing env fallbacks.

## Migration Steps
1. Tighten helpers to prefer context-only and error without it.
2. Adjust bootstrap to set context early and pass paths explicitly.
3. Update validation SystemController to rely on context paths (not env) once bootstrapped.
4. Fix any early callers uncovered by failures (provide config/context injection instead of env).
5. Re-run validation suite and smoke tests to confirm startup and ingestion still work.
