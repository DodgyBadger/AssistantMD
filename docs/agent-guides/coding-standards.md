# Coding Standards

## Language and Tooling
- Python target: `3.12`.
- Formatting/linting: Black + Ruff (`line-length = 88`), with import sorting via Ruff (`I` rules).
- Type checks: MyPy with `disallow_untyped_defs = true`; new functions should be typed.

## Naming
- Modules/functions/variables: `snake_case`.
- Classes: `PascalCase`.
- Constants: `UPPER_SNAKE_CASE`.

## Design Preferences
- Prefer best-practice Python patterns.
- Watch for boilerplate where behavior might drift; suggest refactors when drift risk is high.
- Treat observability as part of done:
  - new features/fixes should add sufficient `system/activity.log` coverage
  - log start/decision/success/failure milestones with structured context (`tag` + `data`)
  - avoid broad exception handling that hides useful diagnostics
