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
- `uv run mypy api core`: 104 errors in 34 of 199 production source files after
  extracting and typing configuration API services. Lint and annotation
  modernization initially produced 663 errors in 80 files.
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
   - Authoring-context assembly batch complete: provider-native message
     restoration, tool-exchange batches, parsed templates, and executable
     sources now retain concrete contracts. Authoring, default-context,
     structured assembly, and tool-passthrough scenarios pass.
   - Authoring-host protocol batch complete: the shared host contract now
     declares the vault, date, buffer, session, and file-state capabilities
     required by helper executors and direct-tool bindings. Authoring, default
     context, and tool-failure scenarios pass.
   - LLM agent/configuration batch complete: parsed model and provider settings
     stay as typed Pydantic models until deliberately serialized, agent history
     and dependency inputs are explicit, and default thinking is narrowed before
     model construction. Model failure, compaction, usage-limit, and session-tool
     scenarios pass.
   - Chat execution batch complete: tool-event sinks agree on keyword-only
     persistence, optional display prompts cross explicit parameters, thinking
     deltas remain independently narrowed, cancellation diagnostics accept
     `BaseException`, and SSE subscriptions retain awaitable task types.
     Streaming, cancellation, manual-retry, and overflow-cache scenarios pass.
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

## API Service Decomposition

`api/services.py` has grown to 5,081 lines and combines approximately one
hundred functions from unrelated API domains. Before resolving its remaining
type backlog, convert it into a package of cohesive modules while preserving
the current import contract.

### Invariants

- `api.endpoints` continues importing public service functions from
  `api.services`; endpoint paths, response models, exceptions, and payloads do
  not change.
- `ChatStore` remains the canonical chat-session boundary.
- Vault Explorer writes, revision restore, and activity rollback continue
  through the existing vault-state mutation and audit services.
- Execution tasks remain process-local runtime state, and workflow history
  remains in the durable workflow-run store.
- Ingestion API entrypoints continue delegating to the ingestion pipeline.
- Typed settings remain separate from secret values. Internal OpenAI OAuth
  state remains hidden behind the dedicated OAuth boundary and generic secret
  APIs do not expose it.
- Persistent `/app/data` and `/app/system` state is not rewritten or reset by
  this structural refactor.

### Target Structure

- `api/services/__init__.py`: stable public re-exports only.
- `api/services/shared.py`: API-service logger, shared chat-store instance, and
  genuinely cross-domain helpers/constants.
- `api/services/vault_files.py`: vault roots, files, revisions, uploads,
  references, Explorer mutations, and workspace path handling.
- `api/services/deferred_reviews.py`: edit proposals and deferred-review
  approval/resume handling.
- `api/services/chat_sessions.py`: session metadata, summaries, detail,
  transcript export, compaction, and deletion.
- `api/services/execution_tasks.py`: task lookup, listing, and cancellation.
- `api/services/vault_state.py`: activity, rollback, snapshot, cache, goal, and
  migration maintenance surfaces.
- `api/services/ingestion.py`: import scans and direct URL ingestion.
- `api/services/workflows.py`: workflow files, lifecycle, execution, scheduler
  projections, and durable run history.
- `api/services/system.py`: status, health, activity log, configuration errors,
  template refresh, and metadata.
- `api/services/configuration.py`: general settings, models, providers, secrets,
  and OpenAI OAuth API projections.

### Implementation Sequence

1. Create the package and shared module, preserving the complete public symbol
   surface through `api.services`.
2. Extract low-coupling execution-task, ingestion, and vault-state maintenance
   groups first; run API import checks and their focused scenarios.
3. Extract workflow and system-status groups; preserve scheduler/runtime
   injection seams and workflow history projections.
4. Extract vault-file and deferred-review groups together where private path
   and mutation helpers are shared.
5. Extract chat-session services while retaining the one shared `ChatStore`.
6. Extract configuration, provider, secret, and OAuth services last so their
   typed settings and confidential-state boundaries can be corrected in place.
7. Remove the monolithic module, verify every endpoint import, then resolve the
   remaining mypy findings within the smaller service modules.

Progress:

- Package boundary established with stable `api.services` imports.
- Process-local execution-task projections extracted and validated.
- API ingestion orchestration extracted with explicit runtime/job contracts;
  core and scheduled ingestion scenarios pass.
- Runtime workflow-loader access and validated vault-path lookup extracted into
  the shared service boundary, preserving facade-private aliases for callers
  still awaiting domain extraction.
- The singleton chat store now lives in shared service state, and durable
  vault-activity groups are projected in their own typed module. Activity
  rollback, mutation recording, and Vault Explorer reference scenarios pass.
- Vault activity listing, rollback preview/execution, snapshot serving, and
  retained-state cleanup now live with that projection and preserve the
  existing `api.services` export surface.
- Manual cache and goal-retention maintenance now live in a dedicated service
  module; cache purge and goal lifecycle scenarios pass.
- System database migration inspection/run projections now share that
  maintenance boundary with a concrete migration-status contract; direct and
  startup migration scenarios pass.
- Packaged system-template refresh now shares the maintenance boundary; the
  seed/refresh scenario passes.
- Retained System Activity query/export now has its own service module; raw
  entries and timestamp strings are validated into API models, and the history
  scenario passes.
- Settings documents, general settings, models, providers, OpenAI OAuth, and
  secrets now live in a dedicated configuration service. Typed settings models
  replace legacy dictionary fallbacks, provider responses are complete at
  construction, and configuration/model/tool scenarios pass.

### Validation

- Import smoke test: `python -c "import api.endpoints; import api.services"`.
- Repository checks: `uv run ruff check .`, `uv run black --check .`, and
  `uv run mypy api core`.
- Focused scenarios after the relevant extraction stage:
  execution tasks/chat cancellation, ingestion, vault file references and
  rollback, workflow lifecycle/history, chat persistence/deferred review, and
  settings/provider/OAuth contracts.
- The maintainer-owned full validation suite remains the final merge gate.

## Next Steps

1. Decompose `api/services.py` behind a stable package export surface.
2. Type each extracted service domain before proceeding to the next.
3. Resolve the remaining small production clusters after API services are
   clean.
4. Run focused scenarios for every extraction and any correction that changes
   executable behavior.

## Next Phase

Feature development for the tooling baseline, followed by refactor and
hardening for subsystem-by-subsystem type corrections.
