# 0028 - Make Execution Principals Explicit

## Status

Accepted.

## Context

AssistantMD currently presents a single-user product, but principal-owned MCP
and provider connections require a stable identity and authorization boundary.
Task source values such as `api`, `tool`, and `scheduler` describe how work
began; they do not identify the actor authorized to use a resource.

## Decision

Use stable `local-user` and `system` principals. Interactive API requests resolve
to `local-user`, while scheduled and system maintenance work uses `system`.
Chat sessions persist an immutable owner. Every execution task captures explicit
authority when created and installs it in context-local state while its worker
runs. Authorization checks live behind shared identity-domain functions rather
than task metadata or transport-provided identifiers.

Principal IDs are persistence contracts. Public API payloads remain unchanged;
the single-user resolver and ownership fields are internal foundations.

## Consequences

- Existing sessions migrate deterministically to `local-user`.
- Background and nested work retain the authority captured at creation.
- Tooling can resolve future principal-owned connections without FastAPI state.
- Multi-user authentication, vault grants, connection storage, and user
  administration remain separate features.
- Task source and execution authority remain distinct concepts.

## Evidence

- Current contracts: `docs/architecture/chat-sessions.md`,
  `docs/architecture/execution-tasks.md`, `docs/architecture/runtime.md`
- Implementation plan: `execution-principal-foundation-plan.md`
