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
  - state/context access
- host-managed off-context state replacing buffer-specific concepts:
  - tools and imports may persist large results into state automatically
  - sandbox code retrieves those artifacts by reference and explores them in Python
  - only selected derived output is routed into context
- `core/authoring` becomes the long-term home for this surface, including built-ins, capability registration, and optional add-ons

This is an architecture search, not a commitment to immediate production rollout. The expected outcome of the next phase is an experimental but coherent authoring path with clear seams for later hardening.

## Scope And Invariants

### In Scope

- define the new authoring model at a high level
- identify the minimum built-in host capability set
- define where capability registration and Monty integration should live
- shape frontmatter as the capability boundary
- preserve the existing DSL unchanged while the new path remains experimental

### Out Of Scope For Initial Pass

- full migration from `python_steps`
- full Monty integration details
- bespoke tool authoring design beyond reserving space for it
- broad validation parity with every existing workflow feature

### Working Invariants

- existing `step` workflows must continue to work unchanged
- the new Python surface should prefer standard Python over custom helper primitives wherever Monty can support it
- host functions, not syntax restrictions, are the primary safety boundary
- large tool/import payloads should stay out of prompt context by default
- frontmatter must remain the source of truth for capability scoping

## Proposed Architecture

### Authoring Surface

A single markdown artifact remains the primary unit:

- YAML frontmatter for capability declaration and defaults
- one executable Monty Python block for orchestration

The authoring contract should stay small and composable:

- `retrieve(...)` for scoped external inputs such as files, state, and recent run history
- `output(...)` for files, state, and context sinks
- `generate(...)` for explicit model calls, with per-call model override inside frontmatter policy
- `call_tool(...)` for declared tool access
- `import_content(...)` for first-class ingestion through the import pipeline

### Capability Model

The host boundary should be pluggable and registry-driven.

- built-in capabilities live under `core/authoring`
- optional capability packs can extend the registry without creating alternate execution paths
- frontmatter resolves to a scoped subset of capabilities for a given authoring artifact or chat session
- each capability owns its own schema, policy checks, and runtime adapter

### State Model

“Buffer” should not remain the author-facing concept.

- local Python variables handle intra-execution flow
- host-managed `state` handles off-context artifacts and persisted transient/session data
- tools and imports may auto-materialize large payloads into `state` and return lightweight refs
- Monty code can inspect and transform state-backed artifacts before sending selected results to `context`

## Likely Landing Zones

Primary home:

- `core/authoring/`

Probable structure:

- `core/authoring/runtime/`
  - Monty runner/session setup
  - capability scoping from frontmatter
  - host-call dispatch and policy enforcement
- `core/authoring/builtins/`
  - built-in `retrieve`, `output`, `generate`, `call_tool`, `import_content`
  - built-in resource/sink handlers for files, state, runs, and context
- `core/authoring/addons/`
  - optional or experimental capability packs
- `core/authoring/contracts.py`
  - capability interfaces and typed boundary models
- `core/authoring/registry.py`
  - registration and lookup of built-ins/add-ons

Current extracted workflow runtime under `core/workflow/` should be reused where possible behind these built-ins rather than duplicated.

## Affected Areas

- `core/authoring/`
  - likely expansion from the current SDK/introspection/service modules into runtime and capability registry layers
- `core/workflow/`
  - shared input/output/tool/execution services may become host adapters behind built-ins
- chat/context-template execution path
  - likely needs a Monty-enabled path for state-backed exploration in chat
- tool and import integration
  - large payload tools should be able to return state refs instead of raw context-heavy payloads
- frontmatter loading/validation
  - new capability-manifest fields for files, state, tools, models, imports, and context

## Tricky Areas To Resolve

- exact frontmatter schema for capability scoping
- whether `state` is backed by existing variable/buffer storage, new storage, or a compatibility layer
- minimum typed object surface returned by `retrieve(...)`
- how much per-call control `generate(...)` exposes for models/thinking/options
- how Monty enters chat execution without destabilizing existing agent flows
- migration strategy for current `python_steps` work:
  - freeze as experimental
  - bridge into the new capability runtime
  - or retire later after a Monty path proves out

## Implementation Outline

### Phase 1: Architecture Skeleton

- create `core/authoring` runtime and registry skeletons
- define capability contracts for built-ins and add-ons
- define draft frontmatter schema for scoped access
- define the v1 built-in function signatures without overfilling them

### Phase 2: Experimental Monty Runner

- add a minimal Monty-backed execution path in `core/authoring/runtime`
- register a stub built-in capability set
- prove host-call dispatch and policy enforcement on a small sample artifact

### Phase 3: Built-In Capabilities

- implement `retrieve(...)` over the highest-value sources first:
  - files
  - state
  - recent runs if needed
- implement `output(...)` for:
  - files
  - state
  - context
- implement `generate(...)`, `call_tool(...)`, and `import_content(...)`
- reuse existing shared runtime under `core/workflow/` wherever it already owns the correct semantics

### Phase 4: Chat/Template Integration

- introduce an experimental path for chat-side Monty execution
- allow large tool/import payloads to materialize into state and return refs
- prove that Monty-based exploration can replace key `buffer_ops` usage patterns

### Phase 5: Authoring UX And Examples

- expose an inspectable capability contract for the new authoring mode
- add a few representative examples:
  - file-based workflow
  - import/research workflow
  - chat/context exploration flow
- tune prompts/templates around the new inspect/write/test/run loop

## Validation Targets

Initial validation should stay narrow and artifact-oriented.

- compile/run smoke test for a minimal Monty-authored artifact
- frontmatter scope enforcement test for file retrieve/output restrictions
- state-ref flow test:
  - tool/import stores large content in state
  - Monty retrieves by ref
  - selected result is emitted to context
- model allowlist enforcement test for `generate(...)`

Maintainers should continue to own full validation runs; agent-side work should stay focused on targeted local checks and scenario additions.

## Next Phase

Next phase: Feature Development.

Immediate goal for that phase:

- sketch the concrete capability contracts and frontmatter schema for the experimental Monty path without yet committing to full implementation detail.
