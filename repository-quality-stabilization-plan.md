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

- `uv run ruff check .`: passes across all 303 Python files after resolving the
  production, root-entry-point, and maintenance-script findings.
- `uv run black --check .`: passes across all 303 Python files after
  normalization.
- `uv run mypy api core`: 191 errors in 42 of 192 production source files after
  typing chat-history provider contracts. Lint and annotation modernization initially
  produced 663 errors in 80 files.
- The largest initial production mypy categories were `arg-type` (228),
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
2. **Mechanical lint and format baseline** — implemented, pending commit
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
   - First batch complete: runtime configuration/background spawning, ingestion
     pipeline/registry, tool utilities, and parser helpers now pass focused
     mypy checks. Authoring-contract and workflow-governor queue scenarios pass.
   - Settings batch complete: YAML secret representers, configuration editor
     models, environment-path projection, and numeric setting coercion now have
     explicit contracts. System template refresh and disabled-tool registry
     scenarios pass.
   - Database/API utility batch complete: central SQLAlchemy factories, raw
     SQLite migration callbacks, API error metadata, and summary/mutation helper
     boundaries are typed. Database migration, startup migration, and API error
     resilience scenarios pass.
   - Runtime/tool contract batch complete: runtime lifecycle returns, built-in
     tool factories, goal/delegate payloads, and workflow vault-path resolution
     are explicit. Goal, workflow lifecycle, session ops, and delegate scenarios
     pass.
   - API transport batch complete: every endpoint has an explicit return
     contract, declared response models are reflected in annotations, multipart
     image uploads are narrowed to actual upload objects, and the mismatched
     deferred-review vault error path uses the service exception's real field.
     The endpoint module now passes production mypy.
   - API service contract work started: deferred-review thinking values,
     Explorer mutation defaults, file-reference paging/scope, and activity
     context iteration now preserve their concrete domain types.
   - Unified logging batch complete: OpenTelemetry sampler inputs, Logfire
     configuration/client handling, span contexts, structured records, and
     instrumentation setup are typed. Warning deduplication now safely
     normalizes structured issue values instead of attempting to hash them.
   - Canonical chat-store batch complete: SQLite connections, row decoding,
     compaction lookup, metadata revision parsing, and provider-part rewriting
     now have explicit contracts. Session persistence, compaction, and tool
     replay scenarios pass.
   - Shared authoring tool-binding batch complete: dynamically loaded tool
     classes, Pydantic AI tool wrappers, async/sync call adapters, and response
     metadata now retain concrete contracts. Authoring contract, tool-failure,
     and disabled-tool scenarios pass.
   - Vault-state ORM batch complete: all manifest, activity, mutation, and
     snapshot models use SQLAlchemy 2 typed mappings while preserving their
     existing tables and columns. This removed legacy column/value ambiguity
     throughout vault-state consumers. Manifest, mutation, rollback, activity
     migration, and startup migration scenarios pass.
   - Ingestion persistence/service batch complete: job models use typed
     SQLAlchemy mappings, importer/extractor adapters retain document types,
     lifecycle methods have explicit outcomes, and settings access fails over
     through one checked lookup boundary. Core and scheduled ingestion
     scenarios pass.
   - Session-operations batch complete: required vault/session identifiers now
     cross one value-returning validation boundary, search candidates avoid
     optional-variable reuse, and summary/index helper results are explicit.
     Session tool, retrieval helper, and persistence scenarios pass.
   - Model-factory batch complete: provider identity survives retry-client
     ownership wiring, provider-specific settings cross explicit typed
     boundaries, retry callbacks are typed, and Grok key absence fails before
     provider construction. Model failure, compaction, and usage-limit
     scenarios pass.
   - Workflow-run batch complete: task lookup, status formatting, cancellation,
     context-message roles, lifecycle event payloads, and virtual-mount metadata
     now retain their concrete contracts. Workflow lifecycle, asynchronous run,
     history, and cancellation scenarios pass.
   - Chat-history provider batch complete: persisted message/tool-event
     normalization, model-message validation, provider identity, and numeric
     limits now cross explicit boundaries. Invalid string limits fail clearly.
     Chat surface, persistence, context passthrough, and tool-history scenarios
     pass.
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

1. Type the API service helpers that feed multiple endpoints.
2. Resolve the vault-state and ingestion service clusters before ORM leaves.
3. Address chat/model-provider protocol mismatches.
4. Run focused scenarios for any correction that changes executable behavior.

## Next Phase

Feature development for the tooling baseline, followed by refactor and
hardening for subsystem-by-subsystem type corrections.
