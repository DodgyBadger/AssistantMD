# Repository Quality Stabilization Plan

## Status

In progress. Baseline captured on 2026-07-25 after the Vault Explorer upload
hardening commit `fa4fbbf`.

## Goal

Make the repository's supported Python surfaces pass one documented, repeatable
Ruff, Black, and mypy workflow before the v0.7 branch freezes, without hiding
real defects behind broad ignores or mixing behavior changes into mechanical
cleanup.

## Baseline

The original configuration was stored in `docker/pyproject.toml` and was not
discovered by root tool invocations. After moving it to the repository root,
the canonical `uv run ...` baseline is:

- `uv run ruff check api core validation`: 1,351 findings, of which 1,202 have
  safe automatic fixes.
- `uv run black --check api core validation`: 209 files would be reformatted
  and 88 already pass.
- `uv run mypy api core`: 658 errors in 80 of 192 production source files after
  adding maintained PyYAML and python-dateutil stubs (down from 668 errors in
  82 files).
- The largest production mypy categories are `arg-type` (228),
  `no-untyped-def` (220), `assignment` (43), `attr-defined` (33), `call-arg`
  (29), `no-any-return` (27), `union-attr` (24), and missing/untyped imports
  (19).
- Before the stub and configuration move, including `validation` raised the
  mypy baseline to 1,055 errors in 182 of 297 files. It will be recounted after
  the production baseline is under control.

## Invariants

- Runtime behavior, API payloads, persistence schemas, validation event
  contracts, and vault mutation semantics remain unchanged unless a type error
  exposes a concrete bug.
- Concrete bugs receive focused behavioral coverage and are kept separate from
  annotation-only or formatter-only changes when practical.
- No blanket `ignore_errors`, broad module exclusions, or unscoped
  `# type: ignore` comments are used to manufacture a clean result.
- Missing third-party typing is handled with maintained stubs or the narrowest
  justified module override; application modules do not become implicitly
  untyped.
- `data/` and `system/` remain untouched as persistent runtime state.
- Maintainers retain ownership of the full scenario suite.

## Contract-Sensitive Areas

- Pydantic API request and response models.
- SQLAlchemy persistence models and subsystem-owned database boundaries.
- Settings parsing, optional values, and provider/model/tool configuration.
- Chat task lifecycle, Pydantic AI protocol implementations, and deferred
  review payloads.
- Vault mutation and rollback state.
- Validation scenarios that implement external protocols or exercise persisted
  contracts.

Relevant architecture decisions include ADR 0001 (runtime composition), ADR
0003 (canonical chat persistence), ADR 0007 (typed settings-backed binding),
ADR 0015 (subsystem-owned databases), ADR 0020 (task-owned chat execution), and
ADR 0025 (durable vault activities).

## Stages

1. **Canonical tooling entry point** — implemented, pending commit
   - Make root invocations load the checked-in configuration consistently.
   - Add maintained typing stubs where they remove import noise without changing
     runtime dependencies.
   - Document the exact narrow commands agents may run.
2. **Mechanical lint and format baseline**
   - Apply Ruff's safe automatic fixes, then review and correct the remaining
     findings.
   - Apply Black in a dedicated, behavior-neutral commit so later semantic
     diffs remain readable.
3. **Production typing foundations**
   - Fix missing annotations and optional-value parsing in small subsystem
     groups.
   - Establish typed SQLAlchemy model usage instead of suppressing column/value
     mismatches.
   - Correct Pydantic construction and settings model types.
4. **Runtime and integration contracts**
   - Fix chat/task, Pydantic AI, model-provider, and tool protocol mismatches.
   - Add focused scenarios only where a type finding reveals a behavioral
     defect or protects a durable boundary.
5. **Validation harness and scenarios**
   - Type the harness before scenario leaves so shared fixes collapse repeated
     failures.
   - Keep experimental probes explicitly scoped if their external dependencies
     cannot provide useful static types.
6. **Freeze checks**
   - Require zero Ruff, Black, and production mypy failures.
   - Drive validation mypy to zero or document narrowly justified experimental
     probe overrides.
   - Run targeted scenarios for behavior-affecting fixes and request the
     maintainer-owned full suite.

## Validation Target

Every stage must pass:

- `uv run ruff check api core validation`
- `uv run black --check api core validation`
- `uv run mypy api core`

Behavior-affecting corrections must also run their closest individual scenario.
The final handoff requests maintainer execution of
`python validation/run_validation.py ...` across the full suite.

## Next Steps

1. Commit the root configuration/tooling baseline separately.
2. Apply Ruff's safe fixes, review the remaining findings, and apply Black.
3. Commit the behavior-neutral lint/format normalization.
4. Recount mypy errors after imports and modern annotations are normalized.
5. Begin production typing fixes by shared foundation rather than raw file
   count.

## Next Phase

Feature development for the tooling baseline, followed by refactor and
hardening for subsystem-by-subsystem type corrections.
