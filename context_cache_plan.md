# Context Manager Step Cache Plan

## Goals
- Add a `@cache` directive for context manager steps to reuse outputs across chat sessions within the same vault.
- Cache should be keyed by vault + template + step and expire by TTL.
- TTL syntax: `@cache 10m`, `@cache 24h`, `@cache 1d`, `@cache 30s` (support s/m/h/d).
- Default scope is vault; no scope flag needed.
- Cache is opt-in only; missing directive means no cache.
- Cache stores content only.
- Cache invalidates on template change via template `sha256` mismatch.

## Design
- **Directive**: `@cache <duration>` parsed by directive registry (new `CacheDirective`).
- **Storage**: store outputs per step in `system/context_manager.db` via `core/context/store.py`.
- **Keying**: use `(vault_name, template_name, step_name)` as key. If multiple steps share the same name, include section index as part of step_id.
- **TTL**: store `created_at` timestamp per cached entry; reuse if `now - created_at < ttl_seconds`.
- **Template invalidation**: store template `sha256` alongside cached step output; treat mismatch as cache miss.
- **Schema**: Safe to drop and recreate context DB tables during development; no migration needed.

## Steps
1. **Add directive**
   - Create `core/directives/cache.py` implementing `@cache`.
   - Parse duration with suffix s/m/h/d; validate value.
   - Register in built-in directives (where others are registered).

2. **Update context store**
   - Modify `core/context/store.py` to persist step-level outputs.
   - Add functions like `get_cached_step_output(...)` and `upsert_cached_step_output(...)` with `created_at` and `template_sha`.
   - Update schema without worrying about preserving existing data.

3. **Wire cache into context manager**
   - In `core/context/manager.py`, read `@cache` per step via directive registry.
   - Before running the step LLM, check cache for `(vault_name, template_name, step_id, template_sha)`.
   - If cache exists and not expired, use cached output and skip LLM call.
   - After a fresh run, store output in cache.

4. **Step identification**
   - Use a stable step id: `f"{idx}:{section.name}"` (already used in section_cache). Persist this as the cache key.

5. **Docs**
   - Update docs to describe `@cache` usage, TTL formats, vault-scoped reuse, and template-change invalidation.
