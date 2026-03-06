# Issue 35 - Goal 1 Plan: Move `pending`/`latest` to `@input` Parameters (Breaking)

## Scope
Adopt a cleaner selection model by moving `pending` and `latest` semantics out of brace substitutions and into `@input` directive parameters.

This is a deliberate breaking change:
- `{pending}` / `{pending:N}` are removed.
- `{latest}` / `{latest:N}` are removed for `@input` file selection.
- `{latest}` as subfolder selector is removed.

Date/time substitutions like `{today}` and `{this-week}` remain supported for path text substitution.

## Design Framing
- Brace/date substitution and globbing define the candidate file set.
- Selector flags (`pending` or `latest`) filter/rank that candidate set.
- Selector modifiers (`order`, `dir`, `limit`, `dt_pattern`, `dt_format`) shape final selection output.
- This separation is intentional: keep deterministic primitives simple and composable, and avoid encoding every edge case into the selector surface.

## Validation-First Contract

### User-visible artifacts
- Selection semantics come from `@input (...)` params and can compose with globs and date substitutions.
- Examples of supported composition:
  - `@input file: clients/Acme* (pending)`
  - `@input file: journals/{this-week}/* (latest, limit=3)`
- `pending` supports deterministic ordering and direction.
- `latest` uses the same ordering engine, with constrained valid order strategies.
- `limit` is applied after selector ordering.
- `filename_dt` ordering requires explicit parse configuration.
- Directory-only input patterns are rejected for `@input file:`; selectors operate on files only.

### Internal artifacts
- Keep `pending_files_resolved` event stable.
- Add minimal selector metadata only where needed for deterministic validation assertions.

### Non-negotiable invariants
- No condition-expression DSL.
- Pending state tracking remains per workflow + selector fingerprint.
- Selector behavior is file-level over resolved candidate files (not folder-first inference).
- `@input file:` never performs implicit directory expansion (no implicit "all files under matched folders").

## Syntax and Semantics (New Primary Model)

### `@input` selector params
- selector flags:
  - `pending` (boolean flag)
  - `latest` (boolean flag)
- selector modifiers:
  - `limit=<int>`
  - `order=<mtime|ctime|alphanum|filename_dt>`
  - `dir=<asc|desc>`
  - `dt_pattern=<regex>`
  - `dt_format=<format>`

### Selector rules
- Exactly one selector mode is allowed: `pending` xor `latest`.
- `(pending, latest)` is invalid in v1.
- `limit/order/dir/dt_pattern/dt_format` are valid only when a selector is present.
- `pending` supports `order` values: `mtime`, `ctime`, `alphanum`, `filename_dt`.
- `latest` supports `order` values: `mtime`, `ctime`, `filename_dt`.
- `latest + order=alphanum` is invalid.
- `latest` default ordering: `order=mtime`, `dir=desc`.
- `pending` default ordering: preserve current behavior (existing default ordering path).
- `filename_dt` requires both `dt_pattern` and `dt_format`.

### Examples
- `@input file: tasks/* (pending)`
- `@input file: tasks/* (pending, limit=5)`
- `@input file: tasks/* (pending, order=mtime, dir=desc, limit=10)`
- `@input file: journals/{this-week}/* (latest, limit=3)`
- `@input file: projects/*/notes.md (latest, order=filename_dt, dt_pattern="...", dt_format="YYYY-MM-DD")`

### Selection pipeline
1. Resolve path substitutions/glob into candidate files.
2. Validate candidates are file targets (not directories).
3. Apply selector mode (`pending` or `latest`).
4. Apply ordering (`order`, `dir`).
5. Apply `limit`.
6. Load selected files.

## File-vs-Directory Rules
- `@input file:` patterns must resolve to files.
- Directory-only patterns (for example `projects/*/`) are invalid and should raise clear errors.
- Users must provide explicit file intent (for example `projects/*/*.md` or `projects/*/notes.md`).
- `latest` and `pending` always operate on the resolved file candidate set.

## State Tracking and Fingerprinting
- Replace raw pattern-string tracking key with normalized selector fingerprint.
- Fingerprint includes:
  - resolved input target expression
  - selector mode (`pending`)
  - relevant selector params that affect selection behavior
- Use canonical serialization to ensure equivalent params map to the same key.

## Breaking Changes and Migration

### Removed forms
- `@input file: tasks/{pending:5}`
- `@input file: journal/{latest}`
- `@input file: journal/{latest:3}`
- `@input file: projects/{latest}/notes.md`

### Migration examples
- `@input file: tasks/{pending:5}` -> `@input file: tasks/* (pending, limit=5)`
- `@input file: journal/{latest:3}` -> `@input file: journal/* (latest, limit=3)`
- `@input file: projects/{latest}/notes.md` -> `@input file: projects/*/notes.md (latest, limit=1)`

### Error UX requirements
- Legacy brace forms fail fast with rewrite guidance in the error message.
- `latest + order=alphanum` returns explicit unsupported-combination error.
- `(pending, latest)` returns explicit unsupported-combination error.
- Directory-only file patterns return explicit file-intent guidance.

## Implementation Steps

1. Add failing scenario assertions first
- Extend/add integration scenarios in `validation/scenarios/integration/core/` for:
  - selector-mode `pending` basics
  - selector-mode `latest` basics (default `mtime desc`)
  - composition with glob and date substitution
  - pending order modes: `mtime`, `ctime`, `alphanum`, `filename_dt`
  - latest order modes: `mtime`, `ctime`, `filename_dt`
  - `asc`/`desc` behavior
  - explicit rejection of directory-only patterns (e.g. `projects/*/`)
  - breaking behavior assertions for removed brace forms with migration messages
  - explicit error for `filename_dt` without `dt_pattern`/`dt_format`
  - explicit error for `latest + alphanum`
  - explicit error for `(pending, latest)`

2. `@input` parameter parsing/validation
- Extend allowed parameter list in `core/directives/input.py` with selector params.
- Enforce selector rules and return actionable errors.
- Reject removed `{pending...}` and `{latest...}` brace usages with migration guidance.

3. Selector pipeline refactor in `@input`
- Resolve candidates first (literal/glob/date substitution).
- Enforce file-only candidate semantics; no implicit directory fan-out.
- Apply `pending` or `latest` as post-resolution selector mode.

4. Ordering engine changes
- Extend `core/utils/file_state.py::get_pending_files(...)` to accept order/direction.
- Reuse ordering machinery for `latest` candidate selection.
- Implement deterministic sort modes:
  - `mtime`
  - `ctime`
  - `alphanum` (pending only)
  - `filename_dt` (`dt_pattern` + `dt_format` required)
- Apply `limit` after sorting/filtering.

5. Event contract updates
- Keep existing event names stable.
- Ensure event payload fields needed by new scenario assertions are present and minimal.

6. Local smoke tests
- Run fast targeted Python smoke tests only (no full validation job).

7. Docs and migration notes
- Update `docs/use/reference.md` and related examples to selector model.
- Add explicit breaking-change migration table for removed forms.
- Document directory-only pattern rejection and explicit file-pattern requirements.
- Document selector-combination constraints.

8. Handoff
- Request maintainer-run full validation and iterate on results.

## Validation Execution Reminder
- Per project guidance, do **not** run `python validation/run_validation.py` in-agent.
- Maintainers run full validation and share results.
