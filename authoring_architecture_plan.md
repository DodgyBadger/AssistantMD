# Authoring Architecture Plan

## Short Spec

We are exploring a pivot from the current constrained Python SDK toward a Monty-backed authoring architecture.

The target shape is:

- one programmable authoring substrate for workflows, context templates, and chat-side off-context exploration
- real Python inside a sandbox, with safety defined by the host capability boundary rather than by a custom AST allowlist
- a small built-in host API exposed to sandboxed code:
  - `retrieve(...)`
  - `output(...)`
  - `generate(...)`
  - `call_tool(...)`
  - `import_content(...)`
- frontmatter as the capability manifest that scopes:
  - readable file subsets
  - writable file subsets
  - import destinations
  - model allowlists/defaults
  - tool allowlists
  - cache/context access
- host-managed off-context cache replacing buffer-specific concepts:
  - tools and imports may persist large results into cache automatically
  - sandbox code retrieves those artifacts by reference and explores them in Python
  - only selected derived output is routed into context
- `core/authoring` becomes the long-term home for this surface, including built-ins, capability registration, and optional add-ons

This is an architecture search, not a commitment to immediate production rollout. The expected outcome of the next phase is an experimental but coherent authoring path with clear seams for later hardening.

## Current Status

The branch has now moved beyond architecture-only planning into an experimental working path.

Recommendation now: commit the current branch state and collapse future Python authoring work onto the constrained-Python contract under `core/authoring` rather than continuing the earlier SDK track.

Implemented so far:

- `core/authoring` runtime scaffolding exists
- built-in capability registry and inspectable contracts exist for:
  - `retrieve(...)`
  - `output(...)`
  - `generate(...)`
  - `call_tool(...)`
  - placeholder for `import_content(...)`
- Monty execution is wired through a real runtime wrapper under `core/authoring/runtime`
- markdown authoring templates load from frontmatter plus one fenced `python` block
- `workflow_engine: monty` is wired into the normal workflow engine loading path
- `retrieve(type="file", ref=..., options=...)` is implemented against the shared workflow input runtime
- `retrieve(type="cache", ref=...)` is implemented against the shared cache runtime in `cache.db`
- `output(type="file", ref=..., data=..., options=...)` is implemented against the shared workflow output runtime
- `output(type="cache", ref=..., data=..., options=...)` is implemented against the shared cache runtime in `cache.db`
- `generate(prompt=..., instructions=..., model=..., options=...)` is implemented against the shared LLM runtime
- `call_tool(name=..., arguments=..., options=...)` is implemented against the existing configured tool-binding/runtime path
  - authoring scope is enforced through `authoring.tools`
  - the current MVP returns inline textual results only
- shared tool binding no longer auto-buffers large results
- chat-side oversized textual tool results are now intercepted via PydanticAI tool-execution hooks
  - large non-file textual results are stored in `cache.db` and replaced with a compact cache-ref/preview notice
  - large vault-backed `file_ops_safe(read)` results are left as file-ref guidance rather than copied into cache
- file/tool boundary hardening is implemented with canonical top-level `authoring.*` frontmatter keys:
  - `authoring.capabilities`
  - `authoring.retrieve.file`
  - `authoring.retrieve.cache`
  - `authoring.output.file`
  - `authoring.output.cache`
  - `authoring.tools`
  - file reads, cache reads, file writes, cache writes, and tool calls are now fail-closed unless explicitly declared
- capability return values already use Pythonic typed objects with attribute access:
  - `source.items[0].content`
  - `draft.output`
  - `written.item.resolved_ref`
  - `tool_result.output`
- a host-provided `date` object is injected into Monty templates to mirror the existing shared token vocabulary in a Pythonic form:
  - `date.today()`
  - `date.tomorrow()`
  - `date.yesterday()`
  - `date.this_week()`
  - `date.last_week()`
  - `date.next_week()`
  - `date.this_month()`
  - `date.last_month()`
  - `date.day_name()`
  - `date.month_name()`
  - each also supports an optional format string such as `date.today("YYYYMMDD")`
- reduced-capability Monty templates now run through the real workflow path
- smoke validation coverage exists through `integration/basic_haiku_workflow`
- deterministic core contract coverage now exists for:
  - authoring host contracts in `integration/core/authoring_contract`
  - chat oversized-tool cache behavior in `integration/core/chat_tool_overflow_cache`
  - chat cache-scoped constrained local execution in `integration/core/code_execution_local`
  - chat metadata visibility for compatibility-vs-preferred tools in `integration/core/chat_tool_metadata_visibility`
  - manual expired-cache purge in `integration/core/cache_manual_purge`

Still intentionally incomplete:

- `import_content(...)` is not implemented yet
- model policy/frontmatter remains intentionally out of scope for now
- chat/context-template integration is not implemented
- stable scenario coverage is still intentionally narrow
- chat now has an initial constrained-Python cache exploration path through the `code_execution_local` tool, but this is still a bridge rather than the final converged chat runtime
- `buffer_ops` still exists for compatibility, but it is now hidden from chat metadata and is no longer the intended exploration path
- recent manual chat testing suggests the runtime bridge is viable, but default chat behavior still needs tuning so the agent prefers deterministic extraction over `generate(...)` when fidelity matters
- cache lifecycle now includes a simple manual purge path via the API, while periodic/background cleanup remains a later hardening step

## Decision

Based on the current end-to-end workflow results, the recommended direction is:

- keep `step` workflows intact
- keep `workflow_engine: monty` as the current constrained-Python workflow path during transition
- stop expanding the earlier SDK/primitives path as a first-class authoring surface
- refactor remaining Python authoring code and docs toward a single source of truth under `core/authoring`
- remove or quarantine branch-local SDK-era introspection and guidance that no longer reflects the chosen model
- treat `core/authoring` as the long-term automation architecture for workflows, context templates, and related authored automations
- deprecate the architectural idea of multiple workflow engines over time, while keeping `workflow_engines/` in place temporarily as a compatibility seam and rollback point

This is no longer just an architecture experiment. The constrained-Python path has now proven:

- better prompt composition ergonomics
- more transparent orchestration in the authored file
- better reuse of the shared workflow runtime
- better LLM authorability from the inspectable contract

The remaining issues found so far have been interface hardening problems, not model failures.

Branch-local consolidation status:

- the retired `python_steps` SDK experiment has now been removed from active runtime paths in this branch
- `core/authoring` no longer serves both the old primitive model and the new constrained-Python contract
- validation scenarios that existed only to prove `python_steps` parity have been removed
- the active Python workflow authoring path is now the constrained-Python contract exposed through `workflow_engine: monty`

Target direction from here:

- converge workflows, context templates, and future chat-side automation on one authoring/automation architecture
- make authored markdown artifacts plus frontmatter the primary unit
- move shared automation/runtime logic under `core/authoring`
- keep `workflow_engines/` only as thin compatibility wrappers until the new shape is proven comfortable

## Scope And Invariants

### In Scope

- define the new authoring model at a high level
- identify the minimum built-in host capability set
- define where capability registration and Monty integration should live
- shape canonical top-level `authoring.*` frontmatter keys as the capability boundary
- preserve the existing `step` DSL unchanged while the new path hardens
- consolidate Python authoring around `core/authoring`
- remove or retire branch-local SDK-era authoring surfaces that are no longer part of the chosen direction

### Out Of Scope For Initial Pass

- full Monty integration details
- bespoke tool authoring design beyond reserving space for it
- broad validation parity with every existing workflow feature

Explicitly out of scope for the immediate cleanup pass:

- removing the `step` workflow engine
- broad migration of existing user workflows
- solving every remaining capability before consolidation

### Working Invariants

- existing `step` workflows must continue to work unchanged
- the new Python surface should prefer standard Python over custom helper primitives wherever Monty can support it
- host functions, not syntax restrictions, are the primary safety boundary
- large tool/import payloads should stay out of prompt context by default
- frontmatter must remain the source of truth for capability scoping
- authored workflow manifests should use canonical top-level `authoring.*` keys rather than nested `authoring:` objects or unprefixed fallback keys
- file scope should be expressed through typed keys that mirror capability usage:
  - `authoring.retrieve.file`
  - `authoring.output.file`
- migration should move shared automation/runtime logic toward `core/authoring` even if temporary compatibility shims remain elsewhere

## Proposed Architecture

### Authoring Surface

A single markdown artifact remains the primary unit:

- YAML frontmatter for capability declaration and defaults
- one executable Monty Python block for orchestration

The authoring contract should stay small and composable:

- `retrieve(...)` for scoped external inputs such as files, cache, and recent run history
- `output(...)` for files, cache, and context sinks
- `generate(...)` for explicit model calls, with per-call model override inside frontmatter policy
- `call_tool(...)` for declared tool access
- `import_content(...)` for first-class ingestion through the import pipeline

### Capability Model

The host boundary should be pluggable and registry-driven.

- built-in capabilities live under `core/authoring`
- optional capability packs can extend the registry without creating alternate execution paths
- frontmatter resolves to a scoped subset of capabilities for a given authoring artifact or chat session
- each capability owns its own schema, policy checks, and runtime adapter
- capability schemas must be inspectable by authoring agents, not only enforced at runtime
- each capability contract should expose structured metadata for:
  - signature
  - supported `type` values
  - `ref` semantics per `type`
  - allowed `options` per `type`, including defaults and valid values
  - return-envelope shape
  - example calls
- `options` dictionaries are allowed in the runtime API only when their schema is explicitly published through this inspectable contract

### Cache Model

“Buffer” should not remain the author-facing concept.

- local Python variables handle intra-execution flow
- host-managed `cache` handles off-context artifacts and persisted transient/session data
- tools and imports may auto-materialize large payloads into `cache` and return lightweight refs
- Monty code can inspect and transform cache-backed artifacts before sending selected results to `context`
- chat guidance should distinguish clearly between:
  - deterministic extraction/verification tasks, which should stay in local code where possible
  - synthesis tasks, which may justify `generate(...)` inside local code

### Context Convergence Sketch

If context templates converge onto the constrained-Python runtime, they should do so
as another invocation mode of the same authoring surface rather than as a special
directive system.

Working direction:

- no implicit history passthrough by default
- context-building scripts retrieve the history they want explicitly
- old concepts like `passthrough_runs` should be treated as transitional compatibility,
  not as long-term primitives

That means the simplest “pass everything through” shape becomes explicit authored code,
for example:

```python
runs = await retrieve(type="run", options={"limit": "all"})
```

with the retrieved history then handed to a dedicated host-side context assembly step.

Important design note:

- `context` should probably not be modeled as an `output(...)` sink
- unlike files or cache, final chat context is not just a destination for raw text
- it needs provider-aware validation, ordering guarantees, and handling of message-part
  constraints such as tool-call/tool-result pairing

Likely direction:

- `retrieve(...)` returns structured run/history/summary material
- Python code selects, filters, and transforms it
- a dedicated host function assembles the final chat history and carries any extra
  instructions intended for the downstream chat agent

This gives us:

- no hidden passthrough behavior
- one explicit model for “what history was included and why”
- one validated place to enforce provider ordering and message-part invariants
- a cleaner separation between:
  - persisted sinks like `file` and `cache`
  - transient assembled chat context

This is still a design sketch, not an implemented contract.

## Likely Landing Zones

Primary home:

- `core/authoring/`

Probable structure:

- `core/authoring/runtime/`
  - Monty runner/session setup
  - capability scoping from frontmatter
  - host-call dispatch and policy enforcement
- `core/authoring/shared/` or equivalent
  - shared source resolution
  - shared sink/output resolution
  - shared tool binding
  - shared execution-prep helpers
- `core/authoring/builtins/`
  - built-in `retrieve`, `output`, `generate`, `call_tool`, `import_content`
  - built-in resource/sink handlers for files, cache, runs, and context
- `core/authoring/addons/`
  - optional or experimental capability packs
- `core/authoring/contracts.py`
  - capability interfaces, typed boundary models, and inspectable capability schemas
- `core/authoring/registry.py`
  - registration and lookup of built-ins/add-ons

Current extracted workflow runtime under `core/workflow/` should be moved under `core/authoring/` over time rather than remaining a second conceptual center.

## Affected Areas

- `core/authoring/`
  - promoted to the canonical home for constrained-Python authoring contracts, runtime, and introspection
- `core/workflow/`
  - expected to shrink as shared authored-automation runtime moves into `core/authoring`
- chat/context-template execution path
  - likely needs a Monty-enabled path for cache-backed exploration in chat
- tool and import integration
  - large payload tools should be able to return cache refs instead of raw context-heavy payloads
- frontmatter loading/validation
  - new capability-manifest fields for files, cache, tools, models, imports, and context
- branch-local SDK-era docs, prompts, and helper exports
  - should be removed, hidden, or clearly downgraded if they no longer reflect the chosen authoring path
- `workflow_engines/`
  - retained temporarily as a compatibility seam, but no longer the desired long-term abstraction boundary

## Tricky Areas To Resolve

- whether any additional scoped frontmatter beyond `authoring.capabilities`, `authoring.retrieve.file`, `authoring.output.file`, and `authoring.tools` is truly needed
- how far to evolve `cache.db` into the shared off-context artifact store without reintroducing persistence sprawl
- minimum typed object surface returned by `retrieve(...)`
- whether the host-provided `date` shim should remain as a durable authoring primitive or later give way to native Monty clock support once `date.today()` and `datetime.now()` are fully implemented upstream
- how much per-call control `generate(...)` exposes for models/thinking/options
- how Monty enters chat execution without destabilizing existing agent flows
- how capability schema introspection should be surfaced in prompts, internal APIs, and authoring tooling
- migration strategy for current `python_steps` work:
  - completed for this branch-local experiment
  - avoid reintroducing partial dual-track authoring guidance
- migration strategy for workflow engines generally:
  - keep compatibility shims for now
  - move real logic into `core/authoring`
  - remove engine-centric architecture only after the new authoring runtime owns the shared execution path cleanly

## Implementation Outline

### Phase 1: Architecture Skeleton

- create `core/authoring` runtime and registry skeletons
- define capability contracts for built-ins and add-ons
- make capability contracts inspectable and structured enough for LLM self-discovery
- define draft frontmatter schema for scoped access
- define the v1 built-in function signatures without overfilling them

Status:

- completed for the current reduced-capability slice

### Phase 2: Experimental Monty Runner

- add a minimal Monty-backed execution path in `core/authoring/runtime`
- register a stub built-in capability set
- prove host-call dispatch and policy enforcement on a small sample artifact

Status:

- completed, then expanded beyond stubs into a working markdown-template execution path

### Phase 3: Built-In Capabilities

- implement `retrieve(...)` over the highest-value sources first:
  - files
  - cache
  - recent runs if needed
- implement `output(...)` for:
  - files
  - cache
  - context
- implement `generate(...)`, `call_tool(...)`, and `import_content(...)`
- reuse existing shared runtime under `core/workflow/` wherever it already owns the correct semantics

Status:

- completed for the file-backed MVP:
  - `retrieve(file)`
  - `output(file)`
  - `generate(...)`
- deferred:
  - `retrieve(runs)`
  - `output(context)`
  - `import_content(...)`

### Phase 4: Chat/Template Integration

- introduce an experimental path for chat-side Monty execution
- allow large tool/import payloads to materialize into cache and return refs
- prove that Monty-based exploration can replace key `buffer_ops` usage patterns

Status:

- partially completed for workflow authoring:
  - chat now inspects `authoring_contract`
  - compile/review loop is usable
- still needed:
  - tighter compile/run authoring loop
  - workflow drafting flow that can self-repair with the current contract

### Phase 5: Authoring UX And Examples

- expose an inspectable capability contract for the new authoring mode
- ensure inspectable capability metadata includes `type`/`ref` semantics, option schemas, return shapes, and examples rather than relying on prose alone
- add a few representative examples:
  - file-based workflow
  - import/research workflow
  - chat/context exploration flow
- tune prompts/templates around the new inspect/write/test/run loop

Status:

- partially completed:
  - inspectable capability contracts exist
  - capability return values already use Pythonic typed objects
  - file-based example workflows exist
- still needed:
  - broader examples beyond file workflows
  - clearer authoring guidance around the transitional host-provided `date` object
  - later UX cleanup once tool/import capabilities land

### Phase 6: Consolidation And Teardown

- commit the current working constrained-Python path as the new baseline
- remove or quarantine SDK-era contract prose and introspection surfaces that no longer serve the chosen path
- refactor `core/authoring` module layout toward the intended long-term structure:
  - contracts
  - introspection
  - loader
  - service
  - runtime/
  - builtins/
- keep reuse with `core/workflow/` explicit and narrow
- avoid leaving two competing Python authoring stories in prompts or API payloads

Validation target for consolidation:

- extend the current smoke path with one more authored workflow scenario
- keep `integration/basic_haiku_workflow` green
- keep the manually-authored weekly planning workflow load/compile/run path working

### Phase 7: Move Shared Runtime Under `core/authoring`

- move shared input resolution from `core/workflow/` into `core/authoring/`
- move shared output resolution from `core/workflow/` into `core/authoring/`
- move shared tool binding and execution-prep helpers into `core/authoring/`
- update `step` and constrained-Python entrypoints to import the shared runtime from `core/authoring`
- keep `workflow_engines/` as thin wrappers only during this phase

Validation target for this phase:

- `integration/basic_haiku_workflow` still passes
- one manually-authored real workflow still compiles, loads, and runs
- no behavior drift in shared file input/output semantics

## Validation Targets

Initial validation should stay narrow and artifact-oriented.

- compile/run smoke test for a minimal Monty-authored artifact
- frontmatter scope enforcement test for file retrieve/output restrictions
- cache-ref flow test:
  - tool/import stores large content in cache
  - Monty retrieves by ref
  - selected result is emitted to context
- model allowlist enforcement test for `generate(...)`

Current implemented validation:

- compile/run smoke checks for Monty-authored artifacts
- end-to-end workflow smoke coverage through `integration/basic_haiku_workflow`
- deterministic host-contract coverage through `integration/core/authoring_contract`
- targeted local checks with `ruff` and `compileall`

Deferred until the system-facing surface hardens:

- full frontmatter scope enforcement scenarios
- cache-ref flow scenarios
- tool/import scenarios
- broader matrix coverage against existing DSL semantics

Maintainers should continue to own full validation runs; agent-side work should stay focused on targeted local checks and scenario additions.

## Next Phase

Next phase: Feature Development.

Immediate goal for the next phase:

- move from architecture search into consolidation and hardening:
  - commit the current authoring path
  - tear down branch-local SDK-era guidance/surfaces that conflict with it
  - move shared runtime inward under `core/authoring`
  - reduce `workflow_engines/` to compatibility shells rather than homes for real logic
  - then continue with scope enforcement and the next capability slice
