# Cache Subsystem Implementation Plan

## Purpose

This plan covers the expanded `cache` subsystem as a shared off-context artifact store for:

- constrained-Python authoring (`retrieve(...)`, `output(...)`, `call_tool(...)`)
- chat-side large tool output protection
- future context-template convergence

The goal is to replace buffer-era concepts and avoid inventing a second temporary
storage abstraction:

- Python locals for ordinary intra-run flow
- `cache` for persisted off-context temporary artifacts

## Why This Is Its Own Effort

The current architecture has two separate legacy mechanisms that are close to, but not
the same as, the desired `cache` model:

- `file_state.db` via [file_state.py](/app/core/utils/file_state.py)
  - currently tracks processed files for `{pending}` selection
- `cache.db` via [store.py](/app/core/context/store.py)
  - currently stores context cache artifacts and summaries

There is also a third legacy concept:

- in-memory buffers via [buffers.py](/app/core/runtime/buffers.py)
  - used for run/session variable routing
  - currently receive oversized tool outputs through [tool_binding.py](/app/core/authoring/shared/tool_binding.py)

This effort should define `cache` as the author-facing abstraction for temporary
off-context artifacts and treat the current DBs/buffers as implementation details to
reuse, migrate, or retire.

It must also align with GitHub issue `#36`:

- [issue #36](https://github.com/DodgyBadger/AssistantMD/issues/36) `chore(database): consolidate store modules into a centralized database layer`

That issue raises a broader persistence-boundary problem:

- multiple system DB files have overlapping concerns
- schema/table registration boundaries are not explicit enough
- table/schema bleed has already been observed

So this plan must not just "pick a DB" for `cache`; it needs to help move the
codebase toward clearer database-layer ownership.

## Current Status

This effort has reached a usable checkpoint.

Implemented now:

- workflow authoring can already pass intermediate values through normal Python variables
- `retrieve(type="file", ...)` and `output(type="file", ...)` are real
- `retrieve(type="cache", ...)` and `output(type="cache", ...)` now exist for the Monty workflow path
- `call_tool(...)` is real and explicit
- file/tool scope is fail-closed through canonical `authoring.*` manifest keys
- cache read/write scope is fail-closed through:
  - `authoring.retrieve.cache`
  - `authoring.output.cache`
- chat overflow now lands in cache refs through chat-side PydanticAI hooks
- `code_execution_local` now provides a least-privilege chat-facing path for cache exploration and small deterministic local transforms
- chat metadata now hides `buffer_ops`
- `buffer_ops` remains compatibility-only for older buffer-era flows
- deterministic coverage now exists in:
  - [authoring_contract.py](/app/validation/scenarios/integration/core/authoring_contract.py)
  - [chat_tool_overflow_cache.py](/app/validation/scenarios/integration/core/chat_tool_overflow_cache.py)
  - [code_execution_local.py](/app/validation/scenarios/integration/core/code_execution_local.py)
  - [chat_cache_multi_pass.py](/app/validation/scenarios/integration/core/chat_cache_multi_pass.py)
  - [chat_tool_metadata_visibility.py](/app/validation/scenarios/integration/core/chat_tool_metadata_visibility.py)
  - [cache_manual_purge.py](/app/validation/scenarios/integration/core/cache_manual_purge.py)

Current transitional stance:

- cache is now the intended off-context artifact layer
- buffers remain only as compatibility infrastructure for older DSL/runtime paths
- chat-side cache exploration works, but chat behavior still needs instruction tuning
- large-text exploration helpers are deferred until prompt/SOP tuning proves insufficient

Recent manual testing showed:

- the cache bridge works in real chat flows
- the model is still too eager to use `generate(...)` inside `code_execution_local`
- direct extraction/verification against cached text gives better fidelity than summary-first handoff
- the next improvement area is behavior/SOP tuning, not more cache substrate work

## Desired Contract

### Author-Facing Shape

`cache` should become a first-class `type` for the existing resource-oriented capabilities:

```python
await output(type="cache", ref="research/browser-page", data=text)
doc = await retrieve(type="cache", ref="research/browser-page")
```

This keeps the surface symmetrical:

- `retrieve(type="file", ...)`
- `retrieve(type="cache", ...)`
- `output(type="file", ...)`
- `output(type="cache", ...)`

Do not introduce a separate cache-write function. The existing resource-oriented
surface is sufficient.

### What Belongs In Cache

`cache` should store host-generated off-context artifacts, not duplicate existing
vault content.

Examples that should usually go to `cache`:

- large web search result sets
- `tavily_extract` output
- browser/crawl extraction output
- broad file-search result blobs
- large derived or aggregated intermediate artifacts created during exploration

Examples that should usually **not** go to `cache`:

- ordinary vault file content already addressable through `retrieve(type="file", ...)`
- large `file_ops` reads where the real artifact is still the vault file ref

For existing vault-backed content, the correct oversize behavior should usually be:

- return refs, metadata, and preview
- signal that the content is large
- switch to scripted exploration against the underlying files

Do not copy vault content into `cache` just to make it inspectable.

### Chat Overflow Policy

Chat should keep automatic context protection, but the destination should become
`cache`, not buffers.

Target behavior:

- common tool execution returns transparent result + size metadata
- chat runtime intercepts oversized tool results before they enter the chat context
- oversized results are persisted into `cache`
- chat receives a lightweight preview/reference
- exploration then happens by generating/running constrained-Python code against
  `retrieve(type="cache", ...)`

Implementation note:

- the shared tool wrapper should not own this policy
- the preferred chat implementation point is PydanticAI tool-execution hooks
  (`after_tool_execute` or `tool_execute`) attached to the chat agent
- this keeps Monty/workflow tool calls transparent while letting chat preserve
  context-window safety
- the current branch upgraded `pydantic-ai` specifically to unlock this hooks API
- this is now implemented for chat:
  - shared tool binding no longer auto-buffers
  - chat intercepts oversized textual tool results after tool execution
  - large vault-backed `file_ops_safe(read)` results are left as file-ref guidance rather than copied into cache
  - other oversized textual tool results are stored in cache and replaced with a compact notice containing a cache ref and preview

Validation coverage:

- deterministic chat overflow contract coverage now exists in
  [chat_tool_overflow_cache.py](/app/validation/scenarios/integration/core/chat_tool_overflow_cache.py)
- deterministic chat metadata coverage now exists in
  [chat_tool_metadata_visibility.py](/app/validation/scenarios/integration/core/chat_tool_metadata_visibility.py)

### Workflow / Monty Policy

Monty should not auto-reroute tool outputs.

Target behavior:

- `call_tool(...)` returns inline result + metadata
- scripts explicitly decide whether to store a result into `output(type="cache", ...)`
- no hidden rerouting in authored Python

### Chat Exploration Guidance Direction

The runtime path is working. The remaining work here is mostly behavioral.

Observed direction from manual testing:

- when the user asks to find, show, quote, verify, or list material from a cached artifact, chat should prefer deterministic extraction over `generate(...)`
- when the user asks to summarize, compare, synthesize, or rewrite, `generate(...)` remains appropriate
- `code_execution_local` should usually try to complete deterministic investigation in one script rather than many tiny exploratory calls

Current next steps:

- tune the default chat template with an explicit extraction-first decision rule
- define an explicit SOP for large-text cache exploration before adding new helper primitives
- defer implementation of deterministic text-exploration helpers for now
- revisit helpers later only when they provide clear value-add beyond ordinary Python string/list operations and when the algorithm quality is something we want to own centrally

### Current SOP Direction For Large Cached Text

When chat or local constrained code explores a large cached text artifact, the working SOP should be:

1. identify what kind of content it appears to be
   - markdown
   - wiki-style markup
   - HTML
   - plain text
   - mixed/unknown
2. orient deterministically before summarizing
   - inspect the start of the text
   - look for headings or other obvious structural markers
   - prefer extracting exact sections or excerpts over immediately calling `generate(...)`
3. use deterministic code for structural navigation where possible
   - find headings
   - isolate likely sections
   - verify whether specific terms or works are actually present
4. use `generate(...)` only when synthesis is actually needed
   - summarization
   - comparison
   - synthesis across multiple extracted sections
5. keep the number of local-code calls low
   - prefer one focused script that orients, extracts, and verifies over many tiny exploratory calls

### Lifecycle / TTL Policy

`cache` must not become a shadow content store.

Therefore:

- `cache` entries should default to expiring
- durable user-owned knowledge should still be written explicitly to vault files
- lifecycle should be part of the core contract, not bolt-on cleanup

TTL semantics should match the existing cache vocabulary where possible:

- `session`
- `daily`
- `weekly`
- explicit durations like `30m`, `24h`

Initial design direction:

- read-time expiration enforcement:
  - expired entries behave as unavailable immediately
- periodic physical purge:
  - expired entries are deleted from storage rather than merely ignored
- metadata should include at least:
  - `created_at`
  - `expires_at`
  - `origin`
  - `cache_mode`
  - optionally `last_accessed_at`

Do not introduce effectively permanent cache entries in the MVP unless there is a
concrete use case that cannot be met by explicit vault output.

Current implementation status:

- read-time expiration is implemented
- opportunistic purge on cache read/write is implemented
- manual physical purge is now available through the API via `/api/system/cache/purge-expired`
- deterministic coverage exists in
  [cache_manual_purge.py](/app/validation/scenarios/integration/core/cache_manual_purge.py)

## Scope Model Direction

The current file-only scope fields:

- `authoring.retrieve.file`
- `authoring.output.file`

will not scale cleanly once `cache` is added.

The likely next manifest shape is type-aware dot notation:

```yaml
authoring.capabilities: [retrieve, generate, output, call_tool]
authoring.retrieve.file: [Tasks/**/*.md, Inbox/*.md]
authoring.retrieve.cache: [research/*, runs/*]
authoring.output.file: [Reports/*.md]
authoring.output.cache: [research/*, scratch/*]
authoring.tools: [browser, file_ops_safe]
```

This is now the preferred scope shape and should be extended rather than replaced as
cache support is added.

## Backend Direction

`cache` should be a logical contract over existing persistence, not a brand-new third
storage concept.

Working assumptions:

- `cache.db` is the likely backend home
- `file_state.db` should remain separate unless future evidence says otherwise
- the authoring/runtime API must not expose backend fragmentation
- payload storage may be hybrid:
  - DB for refs and metadata
  - file/blob backing for large payload bodies if needed

Backend principles:

- authoring sees `cache`
- chat overflow sees `cache`
- backend layout remains an implementation detail
- storage boundaries must be explicit enough to satisfy issue `#36` acceptance criteria

Additional database-layer constraints from issue `#36`:

- inventory current store modules and responsibilities before locking in `cache`
  backend placement
- inventory current SQLite DB files, intended ownership, and actual table contents
- define which DB physically owns new cache artifact tables before shipping the
  contract widely
- prevent further cross-DB schema bleed when adding any new cache artifact tables
- keep schema definitions discoverable from one primary location for the chosen path
- include migration/cleanup planning for any reused DB with misplaced or legacy tables

Do not create a new storage subsystem unless `cache.db` proves inadequate.

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
- deterministic core chat overflow scenario:
  - [chat_tool_overflow_cache.py](/app/validation/scenarios/integration/core/chat_tool_overflow_cache.py)
- likely later integration scenario for cache-backed exploration

## Proposed Phases

### Phase 1: Cache Contract

Define the minimum authoring contract and land the first chat-overflow migration slice.

Deliverables:

- `retrieve(type="cache", ref=...)`
- `output(type="cache", ref=..., data=...)`
- typed result shape for cache retrieval
- initial introspection/docs

Recommended minimal semantics:

- `ref` is a namespaced logical key
- content is text-first for MVP
- metadata is stored and returned
- explicit overwrite/append behavior is defined for cache writes
- entries have explicit lifetime semantics

Status: complete for this phase.

- implemented for constrained-Python workflow authoring
- current MVP supports:
  - `retrieve(type="cache", ref=...)`
  - `output(type="cache", ref=..., data=..., options=...)`
  - `mode=append|replace`
  - `ttl=session|daily|weekly|<duration>`
  - read-time expiry enforcement
  - physical purge of time-bounded expired cache artifacts
  - chat overflow interception via PydanticAI hooks
  - cache-ref/preview responses for oversized non-file textual chat tool results

### Phase 2: Cache Backend Adapter

Implement a narrow backend adapter for the contract.

Deliverables:

- one runtime-owned cache store adapter
- clear mapping to existing DB infrastructure
- workflow/chat origin metadata on writes
- timestamps and basic metadata storage
- lifecycle fields and TTL enforcement
- documented DB/table ownership for the new cache path

Decision point:

- either reuse one existing DB directly
- or add a new logical table in one existing DB while deferring full physical merge

Required precondition from issue `#36`:

- produce a short inventory of existing DB files/store modules and note where the
  new cache artifact tables should live without increasing schema bleed

Non-goal for this phase:

- do not let `cache` become another ad hoc persistence island with its own
  uncodified DB ownership rules

Status: complete for the current MVP.

Notes:

- `cache.db` is now the active backend home
- database ownership was tightened separately under the issue-36 consolidation work
- large-payload blob/file backing is still deferred

### Phase 3: Chat Exploration Convergence

Build the next layer above the migrated overflow path so chat can inspect cache refs cleanly.

Deliverables:

- a chat-scoped constrained-Python exploration tool for cache refs
- examples/docs showing constrained-Python exploration of cache refs in chat
- no active chat guidance that treats `buffer_ops` as the primary exploration path
- a decision on whether any residual buffer infrastructure is still needed after chat exploration converges

Status: initial slice complete.

- initial exploration path now exists through `code_execution_local`
  - tool module: [code_execution_local.py](/app/core/tools/code_execution_local.py)
  - scope: current chat session cache namespace
  - capabilities: `retrieve(cache)`, `output(cache)`, and `generate(...)` inside one Monty snippet
- deterministic contract coverage now exists in:
  - [code_execution_local.py](/app/validation/scenarios/integration/core/code_execution_local.py)
- chat metadata now hides `buffer_ops`
  - `buffer_ops` remains as compatibility infrastructure
  - deterministic visibility coverage exists in
    [chat_tool_metadata_visibility.py](/app/validation/scenarios/integration/core/chat_tool_metadata_visibility.py)

Non-goal for this phase:

- do not redesign Monty `call_tool(...)` into hidden rerouting

### Phase 4: Authoring / Exploration Loop

Use `cache` as the substrate for exploratory scripted inspection.

Deliverables:

- examples/docs showing tool result -> cache -> retrieve(cache) -> generate loop
- a path for chat/codemode to inspect stored artifacts through authored Python

Status: initial bridge complete, broader convergence deferred.

Notes:

- chat can now revisit cache refs across multiple passes
- `code_execution_local` is the current bridge into local constrained-Python exploration
- full chat/runtime convergence is still later work

### Phase 5: Deprecation Cleanup

Once cache-backed overflow works:

- deprecate `buffer_ops` as the primary exploration model
- reduce or remove automatic buffer routing
- document buffers as compatibility-only if still needed temporarily

Status: partially complete.

Notes:

- `buffer_ops` is already hidden from chat metadata
- shared tool binding no longer auto-buffers
- full buffer cleanup is deferred because legacy DSL/runtime paths still depend on it

## Validation Targets

### Early Smoke Targets

- ephemeral smoke:
  - `output(type="cache", ...)` followed by `retrieve(type="cache", ...)`
- ephemeral smoke:
  - large `call_tool(...)` result manually persisted to cache and then revisited

### Stable Scenario Targets

1. Added deterministic core contract coverage in:
   - [authoring_contract.py](/app/validation/scenarios/integration/core/authoring_contract.py)
   - covers `output(cache)` / `retrieve(cache)` and daily cache expiry semantics

2. Added deterministic core chat overflow coverage in:
   - [chat_tool_overflow_cache.py](/app/validation/scenarios/integration/core/chat_tool_overflow_cache.py)
   - covers cache-ref response behavior and persisted cache artifact existence

3. Added deterministic multi-pass chat cache reuse coverage in:
   - [chat_cache_multi_pass.py](/app/validation/scenarios/integration/core/chat_cache_multi_pass.py)
   - proves a stored cache artifact can be revisited without re-running the original oversized tool

## Current Stop Point

For now, this effort is in a good stopping state.

Implemented and usable:

- cache-backed authoring read/write
- chat overflow to cache
- scoped local cache exploration in chat
- multi-pass cache reuse
- manual expired-cache purge

Deferred to later phases:

- periodic/background purge
- large-payload blob/file backing if needed
- helper primitives for text exploration
- buffer/runtime convergence once older DSL paths are retired
- deeper chat instruction tuning based on more real usage

## Risks / Open Questions

### Contract Questions

- what should the MVP `cache` write mode be:
  - replace only
  - append and replace
  - new/versioned
- should `retrieve(type="cache", ...)` be text-only at first
  - recommended: yes

### Backend Questions

- whether `cache.db` schema should expand in place or adopt file/blob overflow immediately
- whether large payloads should live fully in DB rows or in a DB+blob hybrid
- whether cache artifacts should initially land in `cache.db` as a clearly owned
  table family or wait for the broader centralized database-layer refactor from issue `#36`
- what payload-size threshold should switch from inline DB storage to blob/file-backed storage, if any

### Database Consolidation Questions

- how much of issue `#36` must be completed before `cache` ships beyond MVP
- where the centralized database-layer pattern should live so cache artifacts,
  context cache, ingestion jobs, and scheduler jobs do not keep defining schema rules in scattered modules
- what migration/cleanup is needed if existing DBs already contain misplaced tables

### Runtime Questions

- how to expose size metadata from tool calls consistently without reintroducing hidden rerouting
- where exactly the chat overflow interception should sit in `chat_executor`
- what the default TTL should be for:
  - chat overflow artifacts
  - workflow-written cache artifacts
  - session-scoped exploration artifacts

### Scope Questions

- how aggressively to move from the current typed file scope keys:
  - `authoring.retrieve.file`
  - `authoring.output.file`
  to the fuller typed scope family:
  - `authoring.retrieve.cache`
  - `authoring.output.cache`

## Recommendation

Next implementation phase should be **Feature Development** focused on **Phase 3: Chat Exploration Convergence**.

The smallest useful next slice is:

1. define the user-facing chat pattern for exploring cache refs through constrained-Python
2. reduce or remove active `buffer_ops` guidance from chat surfaces
3. add one scenario that revisits the same cached artifact in more than one pass
4. only then decide how much residual buffer/runtime infrastructure can be removed
