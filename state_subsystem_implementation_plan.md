# State Subsystem Implementation Plan

## Purpose

This plan covers the new `state` subsystem as a shared off-context artifact store for:

- constrained-Python authoring (`retrieve(...)`, `output(...)`, `call_tool(...)`)
- chat-side large tool output protection
- future context-template convergence

The goal is to replace buffer-era concepts with a cleaner logical contract:

- Python locals for ordinary intra-run flow
- `state` for persisted off-context artifacts

## Why This Is Its Own Effort

The current architecture has two separate legacy mechanisms that are close to, but not the same as, the desired `state` model:

- `file_state.db` via [file_state.py](/app/core/utils/file_state.py)
  - currently tracks processed files for `{pending}` selection
- `cache.db` via [store.py](/app/core/context/store.py)
  - currently stores context cache artifacts and summaries

There is also a third legacy concept:

- in-memory buffers via [buffers.py](/app/core/runtime/buffers.py)
  - used for run/session variable routing
  - currently receive oversized tool outputs through [tool_binding.py](/app/core/authoring/shared/tool_binding.py)

This effort should define `state` as the author-facing abstraction and treat the current DBs/buffers as implementation details to reuse, migrate, or retire.

It must also align with GitHub issue `#36`:

- [issue #36](https://github.com/DodgyBadger/AssistantMD/issues/36) `chore(database): consolidate store modules into a centralized database layer`

That issue raises a broader persistence-boundary problem:

- multiple system DB files have overlapping concerns
- schema/table registration boundaries are not explicit enough
- table/schema bleed has already been observed

So this plan must not just "pick a DB" for `state`; it needs to help move the codebase toward clearer database-layer ownership.

## Current Situation

### What Already Works

- workflow authoring can already pass intermediate values through normal Python variables
- `retrieve(type="file", ...)` and `output(type="file", ...)` are real
- `call_tool(...)` is real and explicit
- file/tool scope is fail-closed through canonical `authoring.*` manifest keys

### What Still Breaks Down

- large tool outputs in chat are still auto-routed into buffers
- `buffer_ops` is still the exploration mechanism for that routed data
- workflow/chat do not yet share a coherent artifact persistence model
- Monty can inspect a large result once, but has no first-class persisted off-context place to revisit it later

## Desired Contract

### Author-Facing Shape

`state` should become a first-class `type` for the existing resource-oriented capabilities:

```python
await output(type="state", ref="research/browser-page", data=text)
doc = await retrieve(type="state", ref="research/browser-page")
```

This keeps the surface symmetrical:

- `retrieve(type="file", ...)`
- `retrieve(type="state", ...)`
- `output(type="file", ...)`
- `output(type="state", ...)`

Do not introduce a separate `store_state(...)` capability unless this turns out to be necessary later.

### What Belongs In State

`state` should store host-generated off-context artifacts, not duplicate existing vault content.

Examples that should usually go to `state`:

- large web search result sets
- `tavily_extract` output
- browser/crawl extraction output
- broad file-search result blobs
- large derived or aggregated intermediate artifacts created during exploration

Examples that should usually **not** go to `state`:

- ordinary vault file content already addressable through `retrieve(type="file", ...)`
- large `file_ops` reads where the real artifact is still the vault file ref

For existing vault-backed content, the correct oversize behavior should usually be:

- return refs, metadata, and preview
- signal that the content is large
- switch to scripted exploration against the underlying files

Do not copy vault content into `state` just to make it inspectable.

### Chat Overflow Policy

Chat should keep automatic context protection, but the destination should become `state`, not buffers.

Target behavior:

- common tool execution returns transparent result + size metadata
- chat runtime intercepts oversized tool results before they enter the chat context
- oversized results are persisted into `state`
- chat receives a lightweight preview/reference
- exploration then happens by generating/running constrained-Python code against `retrieve(type="state", ...)`

### Workflow / Monty Policy

Monty should not auto-reroute tool outputs.

Target behavior:

- `call_tool(...)` returns inline result + metadata
- scripts explicitly decide whether to store a result into `output(type="state", ...)`
- no hidden rerouting in authored Python

### Lifecycle / TTL Policy

`state` must not become a shadow content store.

Therefore:

- `state` entries should default to expiring
- durable user-owned knowledge should still be written explicitly to vault files
- lifecycle should be part of the core contract, not bolt-on cleanup

Initial design direction:

- read-time expiration enforcement:
  - expired entries behave as unavailable immediately
- periodic physical purge:
  - expired entries are deleted from storage rather than merely ignored
- metadata should include at least:
  - `created_at`
  - `expires_at`
  - `origin`
  - `scope`
  - optionally `last_accessed_at`

Suggested lifetime categories:

- `run`
  - very short-lived
  - intended for one authored execution / one workflow run
- `session`
  - survives across iterative chat exploration in one session
- `temporary`
  - longer-lived but still auto-expiring

Do not introduce effectively permanent state in the MVP unless there is a concrete use case that cannot be met by explicit vault output.

## Scope Model Direction

The current file-only scope fields:

- `authoring.retrieve.file`
- `authoring.output.file`

will not scale cleanly once `state` is added.

The likely next manifest shape is type-aware dot notation:

```yaml
authoring.capabilities: [retrieve, generate, output, call_tool]
authoring.retrieve.file: [Tasks/**/*.md, Inbox/*.md]
authoring.retrieve.state: [research/*, runs/*]
authoring.output.file: [Reports/*.md]
authoring.output.state: [research/*, scratch/*]
authoring.tools: [browser, file_ops_safe]
```

This is now the preferred scope shape and should be extended rather than replaced as state support is added.

## Backend Direction

`state` should be a logical contract over existing persistence, not a brand-new third storage concept.

Working assumptions:

- `state` should be DB-backed
- `file_state.db` and `cache.db` should be evaluated as candidate backends or merge targets
- the authoring/runtime API must not expose backend fragmentation
- payload storage may be hybrid:
  - DB for refs and metadata
  - file/blob backing for large payload bodies if needed

Backend principles:

- authoring sees `state`
- chat overflow sees `state`
- backend layout remains an implementation detail
- storage boundaries must be explicit enough to satisfy issue `#36` acceptance criteria

Additional database-layer constraints from issue `#36`:

- inventory current store modules and responsibilities before locking in `state` backend placement
- inventory current SQLite DB files, intended ownership, and actual table contents
- define which DB physically owns `state` tables before shipping the contract widely
- prevent further cross-DB schema bleed when adding any new state tables
- keep schema definitions discoverable from one primary location for the chosen path
- include migration/cleanup planning for any reused DB with misplaced or legacy tables

Do not finalize a DB merge before the `state` contract is defined.

## Affected Areas

### Contract / Introspection

- [contracts.py](/app/core/authoring/contracts.py)
- [builtins.py](/app/core/authoring/builtins.py)
- [introspection.py](/app/core/authoring/introspection.py)
- [authoring.md](/app/docs/use/authoring.md)

### Authoring Runtime

- [host.py](/app/core/authoring/runtime/host.py)
- [service.py](/app/core/authoring/service.py)

### Tool Execution / Overflow

- [tool_binding.py](/app/core/authoring/shared/tool_binding.py)
- [chat_executor.py](/app/core/llm/chat_executor.py)
- [buffers.py](/app/core/runtime/buffers.py)
- [buffer_ops.py](/app/core/tools/buffer_ops.py)

### Persistence

- [file_state.py](/app/core/utils/file_state.py)
- [store.py](/app/core/context/store.py)
- any shared DB path helpers in [database.py](/app/core/database.py)
- any other `store.py` or DB-backed modules implicated by issue `#36`

### Validation / Scenarios

- existing live routing scenario:
  - [tool_output_routing.py](/app/validation/scenarios/integration/live/tool_output_routing.py)
- current Monty smoke:
  - [basic_haiku_workflow.py](/app/validation/scenarios/integration/basic_haiku_workflow.py)
- likely new integration scenario for state-backed exploration

## Proposed Phases

### Phase 1: State Contract

Define the minimum authoring contract without changing chat overflow yet.

Deliverables:

- `retrieve(type="state", ref=...)`
- `output(type="state", ref=..., data=...)`
- typed result shape for state retrieval
- initial introspection/docs

Recommended minimal semantics:

- `ref` is a namespaced logical key
- content is text-first for MVP
- metadata is stored and returned
- explicit overwrite/append behavior is defined for state writes
- entries have explicit lifetime semantics

### Phase 2: State Backend Adapter

Implement a narrow backend adapter for the contract.

Deliverables:

- one runtime-owned state store adapter
- clear mapping to existing DB infrastructure
- workflow/chat origin metadata on writes
- timestamps and basic metadata storage
- lifecycle fields and TTL enforcement
- documented DB/table ownership for the new state path

Decision point:

- either reuse one existing DB directly
- or add a new logical table in one existing DB while deferring full physical merge

Required precondition from issue `#36`:

- produce a short inventory of existing DB files/store modules and note where the new `state` tables should live without increasing schema bleed

Non-goal for this phase:

- do not let `state` become another ad hoc persistence island with its own uncodified DB ownership rules

### Phase 3: Chat Overflow Migration

Move automatic oversized tool-output interception out of the generic tool wrapper and into chat execution.

Deliverables:

- oversized chat tool outputs stored in `state`
- preview/reference returned to chat instead of buffer manifest
- no new buffer writes for chat overflow

Non-goal for this phase:

- do not redesign Monty `call_tool(...)` into hidden rerouting

### Phase 4: Authoring / Exploration Loop

Use `state` as the substrate for exploratory scripted inspection.

Deliverables:

- examples/docs showing tool result -> state -> retrieve(state) -> generate loop
- a path for chat/codemode to inspect stored artifacts through authored Python

### Phase 5: Deprecation Cleanup

Once state-backed overflow works:

- deprecate `buffer_ops` as the primary exploration model
- reduce or remove automatic buffer routing
- document buffers as compatibility-only if still needed temporarily

## Validation Targets

### Early Smoke Targets

- ephemeral smoke:
  - `output(type="state", ...)` followed by `retrieve(type="state", ...)`
- ephemeral smoke:
  - large `call_tool(...)` result manually persisted to state and then revisited

### Stable Scenario Targets

1. Add a new integration scenario for state-backed authoring:
   - workflow stores a large intermediate artifact to `state`
   - workflow retrieves a subset / second-pass view from `state`
   - final file output exists

2. Update live routing scenario:
   - oversized chat tool output is routed to `state` rather than buffer
   - returned artifact includes preview/reference

3. Add a chat-side exploration scenario later:
   - a stored state artifact is inspected in multiple passes without re-running the original tool

## Risks / Open Questions

### Contract Questions

- what should the MVP `state` write mode be:
  - replace only
  - append and replace
  - new/versioned
- should `retrieve(type="state", ...)` be text-only at first
  - recommended: yes

### Backend Questions

- whether `file_state.db` and `cache.db` should merge now or later
- whether large payloads should live fully in DB rows or in a DB+blob hybrid
- whether `state` should initially land in an existing DB as a clearly owned table family or wait for the broader centralized database-layer refactor from issue `#36`
- what payload-size threshold should switch from inline DB storage to blob/file-backed storage, if any

### Database Consolidation Questions

- how much of issue `#36` must be completed before `state` ships beyond MVP
- where the centralized database-layer pattern should live so `state`, context cache, ingestion jobs, and scheduler jobs do not keep defining schema rules in scattered modules
- what migration/cleanup is needed if existing DBs already contain misplaced tables

### Runtime Questions

- how to expose size metadata from tool calls consistently without reintroducing hidden rerouting
- where exactly the chat overflow interception should sit in `chat_executor`
- what the default TTL should be for:
  - chat overflow artifacts
  - workflow-written state artifacts
  - session-scoped exploration artifacts

### Scope Questions

- how aggressively to move from the current typed file scope keys:
  - `authoring.retrieve.file`
  - `authoring.output.file`
  to the fuller typed scope family:
  - `authoring.retrieve.state`
  - `authoring.output.state`

## Recommendation

Next implementation phase should be **Feature Development** focused on **Phase 1: State Contract**.

The smallest useful slice is:

1. define `state` result and write/read contract
2. inventory existing DB/store boundaries enough to choose a safe initial `state` home
3. implement `output(type="state", ...)`
4. implement `retrieve(type="state", ...)`
5. implement read-time expiration behavior and a minimal purge path
6. verify with ephemeral smoke tests before touching chat overflow behavior

Do not redesign the shared tool wrapper and chat routing in the same first slice.
