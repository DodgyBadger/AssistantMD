# Coding Standards

## Language and Tooling
- Formatting/linting: Black + Ruff (`line-length = 88`), with import sorting via Ruff (`I` rules).
- Type checks: MyPy with `disallow_untyped_defs = true`; new functions should be typed.

## Production Python Quality Gate

The production Python baseline is zero Ruff, Black, and MyPy findings. Every
change that touches production Python must preserve that baseline.

Run the complete gate before committing or handing off:

```bash
uv run ruff check .
uv run black --check .
uv run mypy api core
```

- Targeted checks are useful while iterating, but do not replace the complete
  gate.
- Treat any finding as a regression to fix in the current work. Do not classify
  it as acceptable legacy debt or defer it merely because it is outside the
  lines most recently edited.
- If a finding exposes a materially larger or behavior-sensitive correction,
  stop before committing and report the exact blocker and affected module.
- Do not weaken Ruff, Black, or MyPy configuration to make a change pass.
- Do not add blanket `noqa`, `type: ignore`, per-file exclusions, or untyped
  wrappers. A narrow suppression is acceptable only when the checker cannot
  express a verified external-library boundary; include the specific rule/error
  code and a comment explaining why the suppression is sound.
- Prefer explicit models, protocols, typed collections, and validated boundary
  conversion over propagating `Any`. Use `cast(...)` only where runtime behavior
  or an untyped dependency already guarantees the asserted type.

## Naming
- Modules/functions/variables: `snake_case`.
- Classes: `PascalCase`.
- Constants: `UPPER_SNAKE_CASE`.

## Design Preferences
- Prefer best-practice Python patterns.
- Watch for boilerplate where behavior might drift; suggest refactors when drift risk is high.
- Treat observability as part of done:
  - follow [Activity Logging](activity-logging.md) for `system/activity.log` coverage
  - log start/decision/success/failure milestones with structured context (`tag` + `data`)
  - avoid broad exception handling that hides useful diagnostics
