# Execution Principal Foundation Plan

## Status

Implemented and hardened on `dev/execution-principal-foundation`. The identity,
ownership, runtime propagation, interactive entrypoint propagation, and targeted
branch matrix pass focused validation and the production Python quality gate.
Maintainer full-suite validation remains required before merge.

## Objective

Introduce an explicit principal and execution-authority contract while preserving
AssistantMD's current single-user behavior. Interactive work will run as one
built-in `local-user` principal, and scheduler/system work will run as a distinct
`system` principal.

This slice establishes durable session ownership and authority propagation before
MCP connections are added. It does not add authentication, configurable users,
ACL administration, provider ownership, or any visible product behavior.

## User-Visible Contract

- The UI, routes, request payloads, and response payloads remain unchanged.
- Existing and new chat sessions remain visible and usable exactly as they are
  today.
- Existing provider configuration and `system/secrets.yaml` behavior remain
  unchanged.
- No login, user selector, ownership label, or access-denied state is introduced.
- Scheduled work and interactive work retain their current functional behavior.

## Internal Invariants

1. Every interactive API operation resolves to the stable `local-user` principal.
2. Scheduler- and system-initiated work uses the stable `system` principal.
3. Every chat session has one immutable `owner_principal_id`.
4. Existing chat sessions migrate deterministically to `local-user`.
5. Every execution task carries an explicit authority; authority is not inferred
   from mutable global state after a task is queued.
6. Background workers, gated tasks, retries, and deferred-review resumptions retain
   the authority captured when they were created.
7. Nested tool/workflow execution can read the current execution authority through
   a context-local accessor.
8. Historical task metadata and public API payloads do not become the source of
   authorization truth.
9. Missing or malformed authority fails fast at internal construction boundaries.
10. No authorization decision is based on a display name, email address, vault
    name, request-provided user identifier, or arbitrary task metadata.

## Terminology and Stable IDs

- **Principal**: a stable internal actor identity.
- **Execution authority**: the principal under whose authority one operation runs.
- **Owner**: the principal permanently associated with a durable personal record.
- `local-user`: the only interactive human principal in this slice.
- `system`: the non-human principal used for scheduler and system maintenance work.

The IDs are persistence contracts. They should be centralized constants, not
repeated string literals.

## Scope

### 1. Add the principal domain contract

Create a small identity module under `core/identity/` containing:

- `PrincipalType` with `user` and `system` values.
- Immutable `Principal` with `principal_id`, `principal_type`, and roles.
- Immutable `ExecutionAuthority` carrying the authorized principal identity.
- Central `LOCAL_USER_PRINCIPAL` and `SYSTEM_PRINCIPAL` definitions.
- Normalization and validation helpers for persisted principal IDs.
- A context-local accessor/context manager for the current execution authority.

Keep the contract independent of FastAPI, YAML, databases, providers, and MCP.
Do not add a generic policy language or resource-grant model in this slice.

### 2. Add the single-user request resolver

Add a thin API dependency that returns `LOCAL_USER_PRINCIPAL` for every
interactive request. Route handlers that create, resume, retry, mutate, export,
compact, or delete chat sessions should pass this principal into their service
boundary rather than importing the singleton from domain services.

The resolver is intentionally trivial now. A later auth layer can replace its
implementation without changing downstream service signatures.

Do not accept a principal ID from query parameters, headers, forms, or request
bodies in this slice.

### 3. Persist immutable chat-session ownership

Add `owner_principal_id TEXT NOT NULL` to `chat_sessions`.

- Update fresh schema creation with the new column and an owner lookup index.
- Add a versioned chat-session migration that assigns `local-user` to every
  existing session before enforcing the non-null contract.
- Extend `StoredChatSession` and all row projections with the owner ID.
- Require an owner when a session is first created.
- On subsequent upsert/touch operations, preserve the stored owner and reject an
  attempt to bind the same session to a different owner.
- Session forks inherit the initiating/current principal as owner; under the
  singleton resolver this is behaviorally identical to inheriting the source.
- Ensure deferred-review and compatibility paths do not create session rows with
  direct owner-unaware SQL. Route those paths through the owner-aware session
  contract or provide the captured owner explicitly.
- Keep owner ID out of public API models for now so there is no visible response
  change.

The migration must work for both populated databases and fresh installations.
It must be idempotent through the existing migration ledger.

### 4. Make execution-task authority first-class

Extend runtime task contracts so authority is explicit rather than hidden in
`metadata`:

- Add `authority` to `ExecutionTaskSpec`.
- Add `principal_id` (or the normalized authority projection) to
  `ExecutionTaskSnapshot` and the coordinator's internal record.
- Require the coordinator's task-creation paths to receive validated authority.
- Capture authority before detached work is spawned.
- Install the authority context while `track_current_task(...)` and
  `track_existing_task(...)` own the worker, and reset it reliably on every
  terminal path.
- Preserve authority through queued-to-running transitions and keyed execution
  gates.
- Keep authority out of the public `ExecutionTaskInfo` response in this slice to
  avoid an API change.

Do not use task `source` as identity. `source=api`, `source=scheduler`, and
`source=tool` describe how work began, while authority describes who may act.

### 5. Assign authority at execution entrypoints

Update task-producing entrypoints explicitly:

- Interactive chat starts, manual retries, deferred-review resumptions, manual
  compaction, API workflow execution, and API ingestion use the request's
  `local-user` authority.
- Scheduled workflows, scheduled ingestion, system cleanup, and system refresh
  work use `system` authority.
- Tool-triggered child work inherits the active execution authority.
- If a tool-triggered path has no active authority, fail clearly unless that path
  is an explicitly classified system entrypoint.

For deferred reviews, persist the owner/authority needed for a restart-safe
resume in the durable review record or derive it from the immutable owning
session. Do not resolve the current browser request as a substitute for the
originating authority.

### 6. Expose authority to agent and mutation contexts

- Add the execution authority to `ChatRunDeps` so future provider and MCP
  connection resolution can use it without accessing FastAPI state.
- Make current authority available to built-in tools and authored nested
  execution through the context-local identity accessor.
- Make task-derived vault activity attribution able to read `principal_id` from
  the current task authority without adding new durable vault-state columns in
  this slice. Do not overload existing `source`, `scope`, or `label` fields with
  principal data.

The implementation should prefer one authoritative context propagation path
rather than independently adding `principal_id` parameters to every tool.

### 7. Add a narrow authorization seam

Introduce an authorization service interface with the first stable checks:

- `require_session_access(principal, session)`
- `require_execution_task_access(principal, task)`
- Placeholder/resource-shaped entrypoints for future vault and connection checks
  only if a current call site needs them.

Current policy remains behavior-preserving:

- `local-user` may access all existing vaults and all `local-user` sessions.
- `local-user` retains current administrative visibility in this single-user
  slice.
- `system` is accepted only at explicit system execution boundaries.

Services should call the seam at ownership-sensitive boundaries even though the
single-user decision currently succeeds. Avoid scattering direct comparisons to
`LOCAL_USER_PRINCIPAL_ID` throughout API and domain modules.

## Explicit Non-Goals

- Trusted-proxy or OIDC claim extraction
- User records or users YAML
- Login, logout, invitation, or user-management UI
- Configurable vault grants or filtering
- Session-sharing workflows
- Provider definitions or provider connections
- Principal-owned OpenAI OAuth
- MCP server or connection implementation
- Moving secrets from YAML to encrypted SQLite
- Organizations, groups, teams, or arbitrary roles
- Quotas, billing attribution, or per-user model defaults
- Public API fields exposing owners or principals
- Durable multi-process task identity

## Affected Areas

Expected primary modules:

- New `core/identity/` domain and context helpers
- `api/endpoints.py` and a new API principal dependency
- `api/services/chat_sessions.py`
- `api/services/execution_tasks.py`
- `core/chat/schema.py`
- `core/chat/chat_store.py`
- `core/chat/task_execution.py`
- `core/chat/executor.py`
- `core/chat/deferred_reviews.py`
- `core/runtime/execution_tasks.py`
- `core/runtime/task_runner.py`
- `core/runtime/workflow_governor.py`
- Scheduler, ingestion, compaction, and workflow task entrypoints
- `core/vault_state/activity.py` only where needed to preserve the in-memory
  authority context
- Architecture documentation for chat sessions and execution tasks

Contract-sensitive surfaces:

- Chat-session SQLite migration and schema bootstrap
- Session creation, fork, retry, compaction, and deferred-review resume
- Process-local execution-task snapshots and context variables
- Task lifecycle validation events
- Runtime shutdown/cancellation cleanup
- Task-derived in-memory attribution

## Validation-First Workflow

### Entrypoint hardening matrix

The fixed request resolver must be the interactive authority source. Interactive
service and task adapters must accept the resolved principal or derived
`ExecutionAuthority`; they must not independently import `LOCAL_USER_AUTHORITY`.
System-only bootstrap and scheduler adapters may use `SYSTEM_AUTHORITY` directly.

Cover these branches before declaring the slice complete:

| Branch | Required authority behavior | Required evidence |
| --- | --- | --- |
| Task runner completion, failure, cancellation, and timeout | Captured authority remains stable and context resets | Lifecycle scenario assertions |
| Keyed task gate | Queued and resumed worker retains captured authority | Execution runner scenario |
| API workflow | Uses request principal | Workflow governor scenario |
| Scheduled workflow | Uses `system` even without request state | Workflow governor/scheduler scenario |
| Tool/nested workflow | Inherits active authority and rejects missing authority | Nested workflow scenario |
| Ordinary queued chat | Uses request principal through preflight and run deps | Chat task scenario |
| Uploaded multimodal chat | Uploaded payload reaches preparation under captured authority | Multipart scenario assertion |
| Vault-path multimodal chat | Vault resource resolution occurs under captured authority | Multimodal scenario assertion |
| Retry and deferred-review resume | Derives authority from immutable session ownership | Retry/deferred-review scenarios |
| API ingestion | Uses request principal inside processing task | Ingestion scenario |
| Scheduled ingestion/thread worker | Uses `system` inside `asyncio.to_thread()` | Scheduler ingestion scenario |
| Manual compaction | Uses request principal | Compaction scenario |
| Automatic compaction | Uses `system` | Auto-compaction scenario |
| Tool compaction | Inherits current authority and fails if absent | Tool scenario |

For every applicable execution task, assert `principal_id` remains the same in
created, started, and terminal lifecycle event payloads. Multimodal transport
parsing may occur before task creation, but vault resource resolution, provider
capability checks, agent preparation, and execution must run under captured
authority.

### Primary scenario: `principal_execution_authority.py`

Add a deterministic integration scenario under
`validation/scenarios/integration/core/` before implementation. It should prove:

1. A legacy chat database without the owner column migrates every existing
   session to `local-user` without changing messages or vault binding.
2. A new interactive session persists `owner_principal_id=local-user`.
3. Reopening/touching the session preserves its owner.
4. Attempting to rebind a session to another principal fails without modifying
   the row.
5. An interactive queued chat task records `local-user` authority.
6. The detached worker observes the same authority through the context accessor.
7. A nested task inherits the active authority when using the supported
   inheritance path.
8. A scheduler/system task records and observes `system` authority.
9. Cancellation, failure, and completion all reset the authority context so it
   cannot leak into later work.
10. A deferred-review resume uses the owning/originating authority rather than an
    ambient replacement authority.

Use test doubles and temporary roots; do not call a live model.

### Existing scenario extensions

- Extend the system/chat migration coverage to assert the owner migration is
  idempotent and registered in migration status.
- Extend one existing chat task/deferred-review scenario to assert authority
  survives the real queued/resume adapter boundary.
- Extend execution-task lifecycle assertions to cover principal identity in
  internal snapshots and validation events without changing public API payloads.

### Validation event contracts

Add `principal_id` to existing execution-task lifecycle validation payloads:

- `execution_task_created`
- `execution_task_started`
- `execution_task_completed`
- `execution_task_failed`
- `execution_task_cancelled`
- `execution_task_timed_out`
- `execution_task_skipped`

The key must identify the captured execution authority and remain stable across
the task lifecycle. Do not emit a new event solely for routine principal
resolution; the fixed resolver has no meaningful decision branch in this slice.

### Agent-owned verification

- Run the new targeted scenario directly.
- Run the extended migration, execution-task, chat-task, and deferred-review
  scenarios directly.
- Run focused smoke checks against temporary databases for fresh schema,
  populated legacy migration, and ownership mismatch behavior.
- Run the Production Python Quality Gate from the coding standards guide after
  implementation.
- Request that maintainers run the full validation suite; agents must not run it.

## Documentation Updates

Update current-contract documentation only:

- `docs/architecture/chat-sessions.md`: immutable principal ownership and legacy
  assignment to `local-user`.
- `docs/architecture/execution-tasks.md`: explicit execution authority and
  propagation through queued/background work.
- `docs/architecture/runtime.md`: identity context as runtime execution state.
- Add an ADR recording the single-principal foundation and the distinction
  between task source, execution authority, and durable ownership.

Do not document future claim formats, configurable users, MCP connection grants,
or provider ownership as if they already exist.

## Implementation Order

1. Add failing validation assertions for identity values, session migration, and
   task authority propagation.
2. Add the principal and execution-authority domain contracts.
3. Add the fixed API resolver and system-principal helpers.
4. Add the chat-session owner migration and owner-aware store contract.
5. Make task authority first-class in task specs, coordinator records, snapshots,
   lifecycle events, and context propagation.
6. Update interactive, scheduler, system, nested, retry, and deferred-review task
   entrypoints.
7. Add authority to chat dependencies and expose it to task-derived in-memory
   attribution.
8. Add the behavior-preserving authorization seam at session/task boundaries.
9. Update architecture docs and add the ADR.
10. Run targeted scenarios, smoke checks, and static quality gates; request full
    validation results from maintainers.

## Follow-On Enabled by This Slice

The MCP effort can define every connection with an owner from its first commit:

```text
request principal
    -> authorized MCP connections
    -> principal-filtered deferred ToolSearch catalog
    -> principal-scoped MCPToolset/cache
    -> execution under captured authority
```

Later multi-user work can replace the fixed resolver, add user/grant persistence,
and enforce vault/connection policies without changing the ownership and
authority shape introduced here. Provider connections and encrypted SQLite
secrets remain separate follow-on efforts.

## Next Phase

Proceed to Feature Development using the validation-first order above. Do not
start MCP implementation until this slice's targeted authority and migration
scenarios pass and maintainers confirm the relevant full-validation result.
