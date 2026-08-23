# MCP Client Support Implementation Plan

## Objective

Allow AssistantMD agents to connect to configured Model Context Protocol (MCP)
servers and call their tools. AssistantMD remains an MCP client; exposing an
AssistantMD MCP server is out of scope.

MCP tools are a secondary capability tier. Existing AssistantMD tools remain
immediately visible and retain their current settings, recovery, approval, and
documentation contracts. MCP tool definitions are deferred behind Pydantic AI
tool search so a configured server cannot fill the initial model context with
its complete tool catalog.

This iteration remains a single-user product. The backend persists and resolves
secrets and MCP connections by principal so a later branch can introduce
multiple users without another storage migration, but `local-user` remains the
only interactive principal. The UI does not expose principal creation,
selection, assignment, or administration. The future target is multi-user
within one AssistantMD installation, not multi-tenant infrastructure.

## Implementation Progress

- Slices 1–5 are complete: Pydantic AI contract probes, encrypted
  principal-owned secrets, locked bootstrap and verified YAML retirement,
  workflow ownership, and existing secret-consumer cutover.
- Slice 6 is complete: principal-owned MCP connection persistence, immutable
  slugs, encrypted static credentials, sanitized management APIs, the basic
  single-user System UI, and synthetic-principal isolation coverage.
- Slice 7 is next: managed HTTP/SSE transports, connection readiness/testing,
  network policy, catalog leases, invalidation, and shutdown lifecycle.

## Invariants

- Every MCP server configuration, connection, credential lookup, tool listing,
  and tool call is resolved for an explicit `ExecutionAuthority` principal.
- Interactive configuration always derives its owner from the authenticated
  request authority. In this iteration that resolver returns `local-user`; API
  and UI payloads do not accept or expose an owner selector.
- A principal cannot discover another principal's server names, tool metadata,
  credentials, connection status, or tool results.
- Secret values are stored in an encrypted-at-rest, principal-aware SQLite
  secrets database. MCP credentials never enter normal settings, API responses,
  logs, task metadata, chat history, or model-visible errors.
- Built-in tools remain settings-backed first-class tools. MCP tools do not
  enter the built-in `tools` registry and are not included in built-in tool
  instructions.
- MCP tools use Pydantic AI's MCP client/toolset implementation and are marked
  `defer_loading=True`; `ToolSearch` is the only normal discovery path.
- MCP connections and subprocesses have bounded startup, call, cancellation,
  and shutdown behavior. Runtime shutdown closes all owned MCP resources.
- Server and tool identities are stable and collision-safe across multiple
  configured servers. Persisted tool history must continue to resolve the same
  model-facing name after restart.
- Once discovered, MCP tools use the same call budgets, retry policy, failure
  reporting, output handling, and recovery framework as built-in tools. Their
  secondary status is limited to discovery and initial context exposure.

## Implemented Architecture and Integration Seams

- `ExecutionAuthority` is installed for interactive requests and captured by
  background chat tasks. Session ownership supplies authority when chat work is
  resumed outside the originating request.
- `RuntimeContext` is the process-wide composition root and now owns the MCP
  connection service when encrypted secrets are ready. Current-principal state
  remains context-local.
- Built-in tools are resolved by `core/authoring/shared/tool_binding.py` and
  exposed by `core/llm/capabilities/assistant_tools.py` as a Pydantic AI
  `FunctionToolset`.
- Chat capability assembly occurs in `core/llm/capabilities/factory.py` and is
  shared by initial and deferred-review continuation preparation in
  `core/chat/executor.py`.
- The pinned Pydantic AI 2.19 API provides `MCPToolset`, the `MCP` capability,
  toolset-level `defer_loading()`, capability-level `defer_loading`, and the
  provider-adaptive `ToolSearch` capability. `mcp` and `fastmcp` are present in
  the current lock/environment transitively, but MCP support is not declared as
  an intentional project dependency and should be made explicit.
- Principal-owned credentials are stored in encrypted `system/secrets.db`;
  sanitized MCP definitions and immutable slugs are stored in `system/mcp.db`.
  Normal runtime code has no plaintext YAML fallback.

Relevant decisions: ADR 0001 (runtime composition root), ADR 0007
(settings/tool binding), ADR 0008 (context-efficient disclosure), and ADR 0028
(explicit execution principals).

## Planning-Time Deep Inspection Findings

### AssistantMD execution paths

- Chat is the cleanest first integration seam. Initial and deferred-review
  continuation agents are assembled in `core/chat/executor.py` through
  `build_chat_capabilities(...)`. Queued preflight runs inside captured task
  authority; immediate preflight runs under request authority before the task
  starts and the task later derives authority from durable session ownership.
- Chat tool-event and oversized-output hooks apply to the combined agent
  toolset, so they already observe discovered MCP calls. No MCP-specific event
  or cache pipeline is needed.
- Chat recovery builds its policy table only from resolved built-in `Tool`
  objects, while `PreparedChatExecution.tools` contains only built-in request
  names. Unknown MCP tool names already receive the existing fail-closed
  `UNKNOWN` policy, and normal chat runs retain enabled built-ins, so recovery
  remains conservative in the common case. The rare configuration where every
  built-in tool is globally disabled would make an MCP-only run look tool-free
  to the stream-retry boolean; cover that as hardening by tracking effective
  external-tool presence. The framework-owned `search_tools` call is replay-safe.
- Delegate agents compose tools separately in `core/tools/delegate.py`.
  Compaction and session-summary helper agents intentionally construct
  tool-free agents. MCP must not be added in the global `create_agent` factory.
- User-authored workflows execute tools through the authoring runtime rather
  than the chat capability factory. Workflow MCP access is a separate increment
  after workflow ownership is durable.

### Principal and workflow ownership

- Request authority and chat-session ownership are already explicit and
  context-local. Execution tasks capture authority and reinstall it for workers.
- Scheduled workflows currently fall back to `SYSTEM_AUTHORITY`. Loaded workflow
  definitions, serialized APScheduler job arguments, and durable workflow-run
  records do not contain an owner principal.
- Scheduled `local-user` execution therefore requires coordinated contracts:
  persist `owner_principal_id` on workflow/schedule identity and workflow-run
  history, include it in scheduler arguments, and pass it explicitly to
  `WorkflowGovernor`. The scheduler fallback should then fail closed rather than
  silently granting system or another user's credentials.
- API- and tool-triggered workflows already capture caller authority. Nested
  work must retain that captured authority rather than re-resolve an interactive
  principal.

### Secrets and bootstrap

- YAML secret functions are synchronous and used by model construction, OAuth,
  configuration health, tool binding, web, ingestion, vectors, and logging. The
  encrypted service should retain narrow synchronous lookup/presence methods so
  migration does not force async access through all those paths.
- Normal lookups should derive principal scope from context-local
  `ExecutionAuthority`. Bootstrap and installation services must pass explicit
  system scope; missing authority must never default to `local-user`.
- Bootstrap currently validates settings (and reads secrets) before managed
  database migrations. Encrypted-store initialization and the one-time YAML
  import must occur in a pre-validation secrets-bootstrap phase, or startup must
  be reordered so no configuration/logging lookup occurs before the master key,
  system root, and encrypted store are ready.
- `secrets.db` must be registered in `core.database.SYSTEM_DATABASES` and the
  managed migration registry for later schema versions. The first cross-store
  YAML import also needs a recorded completion marker because the current
  orchestrator only upgrades declared SQLite targets.
- Validation currently isolates secrets with `SECRETS_PATH`. It must instead
  provision an isolated master key and system-root database; retaining
  `SECRETS_PATH` would preserve an accidental plaintext compatibility contract.
- No installer currently generates an encryption setting. Development setup,
  container examples, CI seeding, and validation startup need key provisioning.
  The encryption library must be a direct dependency even if present transitively.

### Pydantic AI MCP and tool search

- `MCPToolset` produces normal `ToolDefinition`s, handles tool-list change
  notifications, and opens/closes its FastMCP session with the agent toolset.
  AssistantMD creates a fresh agent per chat run, but reconnecting every enabled
  server before every first model request would add avoidable latency. The
  runtime should retain principal-scoped clients and lend each run a frozen
  catalog snapshot rather than relying on the raw agent-owned lifecycle.
- Capability-level `defer_loading=True` is the wrong primitive here. It adds a
  `load_capability` catalog/tool, and loading one MCP capability reveals every
  tool owned by that server. A local probe confirmed this on Pydantic AI 2.19.
- The correct composition is a non-deferred `MCPToolset` wrapped with
  `filtered(...)` for the optional allowlist, `prefixed(...)` for collision-safe
  names, `defer_loading()` for individual definitions, and
  `with_metadata(...)` for provenance, exposed through Pydantic AI's `Toolset`
  capability. One `ToolSearch` covers the combined deferred corpus. A probe
  confirmed that built-ins and `search_tools` are initially visible, one
  discovered prefixed tool becomes visible on the next request, and its
  undiscovered sibling remains hidden.
- Discovery persists as typed Pydantic AI history keyed by exact model-facing
  tool name. Prefixes are therefore persistence identifiers. Give each
  connection an immutable, principal-unique slug generated from its initial
  name, separate from its editable display name, and never reuse a retired slug.
  Model-facing names use Pydantic AI's conventional
  `<connection_slug>_<server_tool_name>` format within provider naming limits.
- `PrefixedToolset` maps calls back to the original server name. Apply the
  allowlist before prefixing; lock the filter -> prefix -> defer -> metadata
  wrapper order with a contract scenario.
- AssistantMD's current `PrepareTools` hook applies globally and overwrites
  `assistantmd.source` with `settings`. It must preserve preclassified MCP
  provenance or select only built-in definitions once both share an agent.
- Tool search is provider-adaptive. Unsupported models see a local
  `search_tools` function and no deferred schemas. Supporting OpenAI/Anthropic
  models receive provider-native deferred definitions: this protects active
  prompt exposure, though the provider still receives the deferred search corpus.
- Every raw combined toolset is entered before the first model request. Deferred
  search does not defer network initialization/tool listing. A principal-scoped
  manager must therefore settle enabled connections before agent construction
  and expose catalog-backed toolsets; `ToolSearch` alone does not provide
  readiness or failure isolation.
- `MCPToolset` defaults remote tool errors to `ModelRetry` and inherits the agent
  retry count. Override that default with `tool_error_behavior="failed"` so a
  server-declared execution failure becomes one model-visible failed tool result
  and does not introduce an automatic MCP-only retry loop. Argument validation
  retains Pydantic AI's normal retry behavior; transport failures retain
  AssistantMD's existing timeout, reporting, and recovery paths. The model or
  workflow may deliberately call the tool again.

### MCP authentication and network policy

- Static bearer tokens and headers can be resolved from the encrypted
  principal/connection namespace when constructing a managed client.
- FastMCP's `auth="oauth"` default is not product-ready: it keeps tokens in
  memory and opens a browser/loopback callback from the backend. Principal-owned
  MCP OAuth needs custom FastMCP token storage backed by the encrypted database
  plus AssistantMD API/UI start, callback, status, disconnect, and refresh paths.
- MCP OAuth is part of the first vertical slice. Follow the existing OpenAI OAuth
  product pattern for headless deployments: persist short-lived pending state,
  return an authorization URL to the frontend, accept a normal callback when the
  AssistantMD endpoint is reachable, and provide manual redirect completion when
  it is not. Reuse or extract shared PKCE/state, pending-flow, redirect parsing,
  expiry, redaction, and UI-status helpers. Keep OpenAI-specific endpoints,
  payloads, and device-code behavior separate; an MCP server may not advertise a
  device flow.
- The existing outbound URL policy rejects loopback/private addresses, so MCP
  needs its own explicit policy: HTTPS for non-loopback targets, permitted local
  development HTTP, credential-free URLs, DNS-rebinding defenses, and sanitized
  logs. Containers also need a documented route to host-local services because
  container `localhost` is the container itself.

## Proposed Shape

### 1. Principal-owned connection domain

Add a dedicated `core/mcp/` subsystem with typed contracts and a service owned
by `RuntimeContext`. Its public operations accept or require the current
`ExecutionAuthority`; callers do not supply arbitrary owner IDs.

Persist sanitized connection definitions in a subsystem-owned SQLite database
under the configured system root. Each row includes an immutable connection ID,
owner principal ID, display name, enabled state, transport configuration,
non-secret policy, and timestamps. All unique constraints and queries include
the owner where appropriate.

Replace `system/secrets.yaml` with a subsystem-owned encrypted-at-rest SQLite
secrets database. The secrets service is a shared platform boundary, not an
MCP-only store: existing provider/API secrets and new MCP credentials both use
it. Secret records carry an owning principal (or an explicit system/global scope
for infrastructure secrets), a stable namespace/key, encrypted value material,
and lifecycle metadata. MCP keys should be scoped by immutable connection ID,
for example `(principal_id, "mcp", connection_id, credential_name)`.

Model API keys, provider base-URL credentials, and provider OAuth state are also
principal-owned in the new schema. Runtime model/provider construction resolves
them through the active execution authority. During this iteration all
interactive provider and MCP credentials therefore resolve under `local-user`;
all user-authored workflows also execute on behalf of `local-user`, regardless
of whether they were started by the API, a schedule, or another tool. Their
model, web, OCR, and eventual MCP credential lookups therefore use the same
principal scope. True installation maintenance remains `system` work and cannot
read user-owned secrets merely because it runs in the same process.

Workflow definitions and schedules must retain an owner principal in their
durable contract even while the only possible owner is `local-user`. Later
multi-user work can then resolve schedules and workflow-triggered child work
under that stored owner without changing the workflow execution model.

The service must centralize encryption/decryption, key lookup, atomic writes,
redacted enumeration, ownership checks, and migration. Callers receive secret
values only through narrow runtime lookup methods; persistence and generic API
layers expose presence/status metadata. Do not copy per-user values into the old
YAML namespace or use prefixed YAML keys as isolation.

Key material must remain outside the encrypted database. The implementation ADR
must define rotation/versioning, startup behavior when the key is absent or
wrong, backup/restore expectations, and file permissions. Initial installation
requires one user-generated installation-level master key in the deployment's
`.env` file; `.env.example` and platform-specific secure generation commands
make that step explicit.
Production/container deployments may inject the same environment setting through
their normal mounted-secret or environment-secret mechanism. The `.env` file and
master key must remain uncommitted and outside persistent application data. No
silent plaintext fallback is allowed.

Each secret record uses authenticated encryption with a fresh random nonce and
stores a key-version identifier. The first release needs one active key and an
explicit rotation operation; it does not need per-principal encryption keys.
Missing/wrong keys or failed ciphertext authentication enter an explicit locked
state: API/UI diagnostics remain available, but model/provider execution and
secret mutation are disabled and migration does not run. A usable backup
consists of both the SQLite database and the separately protected installation
key.

Use AES-256-GCM through a directly declared `cryptography` dependency. Bind each
ciphertext to its principal, namespace, and secret name as authenticated
associated data. Installation instructions have the user generate the first
32-byte random key directly into `.env` without printing it. AssistantMD never
replaces an existing key implicitly. Rotation adds a generated next-version key,
re-encrypts and authenticates every row in one transaction, then retires the
prior version only after verification.

Key loss affects credentials only, not vaults, chats, workflows, or other user
content; recovery is re-entry/reconnection. Setup must clearly report that the
key is stored in plaintext in `.env`, that a database backup does not include
it, and that losing it requires all secrets to be re-entered or reconnected.
AssistantMD provides no key export, download, or managed key-backup feature.
Users may back up `.env` themselves if desired and are responsible for protecting
that copy; possession of both the database and key provides access to secrets.

Principal scope must be part of repository keys, uniqueness constraints, cache
keys, OAuth pending-state correlation, and authorization queries—not a filter
added only at the API layer. Service methods should normally derive the
principal from `ExecutionAuthority`; narrowly scoped migration/system methods
may name an owner explicitly and must not be reachable through normal user
payloads. Avoid tenant IDs, tenant tables, cross-tenant routing, or tenant-level
key hierarchies: those are not part of the intended future product.

### 2. Connection and transport policy

Start with URL-connected Streamable HTTP/SSE servers, whether hosted remotely or
already running on the local machine/network. Non-loopback connections require
HTTPS. Plain HTTP is permitted only through an explicit development allowance
for loopback endpoints. Treat stdio servers launched by AssistantMD as a separate
hardening increment because command execution, environment inheritance,
filesystem access, process ownership, and container deployment require an
explicit allowlist and sandbox policy.

This means local services such as Marimo or Docling are in scope when deployed
independently with an MCP HTTP/SSE endpoint. AssistantMD connects to that endpoint
but does not install, start, or supervise the local server process in this
iteration.

Connection construction resolves credentials only at execution time and builds
Pydantic AI MCP clients with bounded initialization/read timeouts. Do not enable
MCP sampling, elicitation, roots, prompts, or resources in the first tool-only
slice. Server-provided instructions should remain disabled initially so remote
content is not silently promoted into system instructions.

Add a lazy principal-scoped connection manager to `RuntimeContext`. It owns
FastMCP clients keyed by principal, immutable connection ID, and configuration
version; enabling/testing may warm a connection, but application startup does
not connect to every server. Concurrent cold requests share one initialization
future, and different cold connections initialize concurrently. Configuration,
credential, disable, and delete events invalidate/close the affected client.
Idle clients close after a bounded timeout and runtime shutdown closes all.

Before constructing an agent, acquire a settled MCP tool snapshot for every
enabled connection. This readiness barrier returns only `ready` connections and
explicit sanitized `unavailable` results—never unresolved `connecting`, `stale`,
or `reconnecting` state. Apply bounded transient reconnection before settling a
connection unavailable; the next chat run tries again. One unavailable server
must not remove built-ins or healthy connections.

Freeze tool definitions/catalog versions for the run and route calls through
leases on the managed clients. Server tool-list-change notifications mark the
manager catalog stale for the next run rather than mutating the current run's
search corpus. Active leases prevent idle eviction; explicit disable/delete or
credential revocation may invalidate them. A compact model-visible note and
chat warning event identify unavailable connection display names without
transport or credential details. Consequently, a tool-search miss can never
mean that connection initialization was merely pending.

Enabled connections are principal-global in this iteration. Once `local-user`
enables a Gmail, Marimo, Docling, or other connection, it is available for tool
search from any of that user's chats without per-vault or per-session attachment.
The connection-level enabled flag is the primary availability control. Future
chat/workflow/vault policy may narrow access without moving or duplicating the
principal-owned credentials.

### 3. Second-class tool exposure

Create an AssistantMD MCP capability builder alongside
`assistant_tools.py`. For each enabled connection visible to the active
principal, acquire its managed client/catalog lease and expose a catalog-backed
Pydantic AI toolset. Filter original names through the optional allowlist,
prefix model-facing names with the immutable connection slug, mark individual
tools deferred, and attach MCP provenance metadata. Do not defer the MCP
capability itself.

Compose one Pydantic AI `ToolSearch` capability around the deferred MCP corpus.
Use the provider-adaptive default initially, which supplies native search on
supported providers and local keyword search elsewhere. Built-in AssistantMD
tools remain non-deferred and outside this search corpus.

Add AssistantMD metadata to discovered MCP definitions (`source` and sanitized
connection ID/name) so existing logging, history, and tool-policy paths can
classify them without creating a parallel reporting contract. Enforce an upper
bound on search results and reject name collisions or reserved `search_tools`
conflicts at preflight.

An enabled connection trusts all tools reported by its server by default. A
connection may optionally persist an `allowed_tools` list, which Pydantic AI
applies before the tools enter the deferred search corpus. Missing/empty policy
means all tools; a populated list exposes only exact matches. AssistantMD does
not infer read-only versus mutating behavior from untrusted names/descriptions,
and built-in `file_write` review policy does not extend implicitly to MCP calls.
The UI must make the trust consequence of enabling a server clear.

### 4. Execution, history, and recovery

Pass principal-derived MCP capabilities into every construction of a chat agent,
including deferred-review continuations and retry/restart paths. Discovery
messages and later MCP tool calls remain normal provider-native Pydantic AI
history so the existing chat persistence contract is preserved.

Extend tool activity classification and output caching to recognize MCP calls,
then route them through the same rate limits, retry policy, failure reporting,
bounded previews, off-context output cache, and recovery machinery as any other
tool. Pydantic AI MCP defaults must not introduce a separate automatic retry
contract. Connection headers and credential values remain redacted from logs and
errors. MCP mutation approval is out of scope; existing inline-edit review
continues to apply only where the normal tool policy explicitly requests it.

### 5. Configuration API and UI

Add principal-scoped endpoints and service methods to list, create, update,
enable/disable, test, and remove MCP connections, plus set/clear credentials.
Responses expose only sanitized connection metadata and credential-presence
flags. Mutations use the request authority installed by the API router and
cannot accept an owner override.

Add a settings UI section that manages the same contract. Connection testing is
explicit, bounded, and reports sanitized initialization/tool-list status. UI/API
work follows the domain service so isolation is enforced below the transport
layer rather than only in endpoints.

For this iteration the frontend presents one undifferentiated set of model,
OAuth, secret, and MCP settings for the current user. It does not display the
`local-user` implementation identifier or provide user-management controls.
Connections are configured and enabled once rather than attached to individual
chats or vaults.
Later multi-user work should change request-principal resolution and add an
authentication/user-management surface without changing the secret or MCP
ownership schema.

## Delivery Slices

Each slice is an independently testable milestone and a candidate commit
boundary. Complete its targeted checks before beginning the next slice;
maintainers retain ownership of the full validation suite. The detailed work
inventory below supplies the requirements assigned to these slices.

1. **Contract probes and ADRs**
   Lock down the Pydantic AI composition, accepted failure behavior, immutable
   naming contract, encrypted-store design, HTTP/SSE behavior, and feasibility
   of the encrypted FastMCP OAuth adapter and headless completion flow.

2. **Encrypted secrets store foundation**
   Implement the principal-aware schema and service, AES-256-GCM envelope,
   key-version and rotation primitives, atomic CRUD/presence operations, tamper
   detection, redaction, and principal/system isolation. This slice does not
   migrate existing consumers.

3. **Bootstrap and one-time YAML migration**
   Supply `.env.example` and documented secure key-generation commands,
   initialize the database before secret consumers run, implement the
   transactional/idempotent YAML import and ledger, update validation isolation,
   and cover fresh, successful-upgrade, failed-upgrade, locked-secrets, and
   restart paths. Missing or unusable keys keep the API/UI available but disable
   model/provider execution and secret mutation; they never select plaintext
   storage or mutate/migrate existing secret state. Implement and validate the
   importer in this slice, but activate YAML retirement only with slice 4's
   final consumer cutover so no runnable milestone deletes the file while live
   code still depends on it.

4. **Workflow ownership foundation**
   Persist and propagate immutable workflow ownership, seed existing workflows
   as `local-user`, remove implicit scheduler system authority, and prove API-,
   tool-, and schedule-triggered ownership. This establishes the prerequisite
   but does not yet expose MCP tools to workflows.

5. **Existing secret-consumer migration**
   Move model/provider configuration, OAuth state, configuration health, tool
   binding, web, ingestion, vectors, and logging onto authority-aware encrypted
   lookups. Remove runtime YAML compatibility and activate verified YAML
   retirement only after every consumer and scheduled execution owner is
   covered.

6. **MCP connection domain and basic management UI**
   Add principal-owned connection persistence, immutable slugs, allowlists,
   encrypted static credentials, authorization-aware services/endpoints,
   credential-presence reporting, enable/disable/delete semantics, sanitized
   test contracts, and synthetic-principal isolation checks. Add the single-user
   UI for URL/transport settings, display name, allowlist, static credentials,
   enable/disable, and deletion. Define the connection-test response contract in
   this slice, but add the working UI action with the transport manager.

7. **MCP transport and connection manager**
   Implement Streamable HTTP/SSE clients and the lazy principal-scoped manager,
   including readiness barriers, shared initialization, frozen catalogs, leases,
   invalidation, idle/shutdown cleanup, and unavailable-server isolation. Build
   HTTPS, loopback-development, DNS-rebinding/SSRF, timeout, response-size,
   concurrency, and redaction controls into this slice rather than postponing
   them to final hardening. Add the connection-test UI action, wire it to this
   runtime, and return sanitized tool-list/readiness results.

8. **Chat tool-search vertical slice**
   Compose filtered, prefixed, individually deferred MCP tools with `ToolSearch`;
   preserve provenance and integrate initial/continued chats, budgets, events,
   output handling, cancellation, caching, recovery, and history replay. Finish
   with a UI-configured credential-free or static-credential local HTTP MCP chat
   smoke test.

9. **MCP OAuth and OAuth management UI**
   Deliver encrypted token storage, PKCE/state and pending-flow handling,
   callback plus headless manual completion, refresh/disconnect/status, and the
   OAuth-specific additions to the existing connection UI: connect URL/status,
   callback/manual completion, refresh, reconnect, and disconnect. Finish with a
   user-level smoke contract for a remote OAuth service such as Gmail.

10. **End-to-end hardening and documentation**
    Verify cross-principal isolation, malformed servers, cancellation/shutdown,
    redaction, list changes, collisions, oversized results, security controls,
    dependencies, and container packaging. Document the current contract and
    request the maintainer-owned full validation run before review preparation.

## Detailed Work Inventory

The following requirements are allocated across the delivery slices above. They
are a completeness inventory, not additional sequential milestones.

- **Contract probes and decisions**
   - Add an experimental scenario proving Pydantic AI 2.19 behavior for multiple
     toolset-level deferred MCP toolsets, stable prefixing, allowlist wrapper
     order, local/native search request shapes, history replay, cancellation,
     remote tool retry behavior, and failed initialization. Explicitly prove
     that capability-level deferral is not used.
   - Specify the encrypted SQLite secrets schema, authenticated-encryption
     envelope, master-key source, key versioning/rotation, and principal/system
     ownership rules in an ADR.
   - Verify the accepted immutable connection-slug naming rule and record its
     replay implications.
   - Confirm URL transport behavior and Pydantic AI/FastMCP compatibility for
     Streamable HTTP, legacy SSE, HTTPS enforcement, and loopback development
     HTTP. Stdio is explicitly outside the first release.
   - Probe a custom encrypted FastMCP token-storage adapter and
     AssistantMD-owned headless-safe browser callback/manual-completion flow; do
     not use the in-memory/backend-browser `auth="oauth"` shortcut.
   - Identify reusable OpenAI OAuth helpers for PKCE/state, pending-state expiry,
     redirect parsing, redaction, and sanitized status without coupling MCP to
     OpenAI's provider-specific token or device-code protocol.

- **Encrypted secrets platform migration**
   - Add the encrypted SQLite secrets store and principal-aware service contract,
     including explicit system/global ownership for existing infrastructure
     secrets.
   - Migrate existing secret consumers away from direct YAML access while
     preserving their narrow lookup/presence contracts.
   - Route model API keys, provider base-URL values, OAuth connected state, and
     OAuth pending state through principal-aware lookups. Keep internal OAuth
     entries hidden from generic secret enumeration.
   - Provide a one-time, fail-fast migration path from `system/secrets.yaml` that
     imports non-empty static secrets in one transaction, reads back and
     authenticates every value, and removes the live plaintext file only after
     verification succeeds. Failed migration leaves the YAML untouched and does
     not record completion.
   - Assign configured model/provider/tool secrets and unknown user-defined
     entries to `local-user`; assign known operational credentials such as
     `LOGFIRE_TOKEN` to `system`. Do not migrate OAuth tokens or pending OAuth
     attempts: discard pending state and require a fresh principal-bound OAuth
     connection after upgrade.
   - Implement this as a versioned, idempotent system migration recorded in the
     existing migration ledger. It remains available for installations upgrading
     from older releases but performs no work after successful completion. If no
     YAML exists, initialize the encrypted store and mark the migration complete.
     Normal runtime code has no YAML compatibility fallback and never recreates
     `system/secrets.yaml`.
   - Cover missing/wrong keys, tampered ciphertext, atomic updates, redaction,
     backup/restore, and key rotation. Never commit key material or populated
     secret data.
   - Reorder bootstrap so encrypted-store initialization/import precedes every
     configuration health or logging lookup, and replace validation's
     `SECRETS_PATH` isolation with per-run database/key isolation.

- **Workflow ownership foundation**
   - Add immutable `owner_principal_id` to loaded workflow/schedule identity,
     serialized scheduler job arguments, workflow execution tasks, and durable
     workflow-run history.
   - Seed all existing/user-authored workflows as `local-user` in this branch,
     pass scheduler authority explicitly, and remove implicit scheduler fallback
     to `SYSTEM_AUTHORITY`. Keep true installation jobs explicitly system-owned.
   - Prove API-, tool-, and schedule-triggered workflow work retains owner
     authority through nested/background execution and secret lookup.

- **Principal-owned MCP persistence and runtime service**
   - Add connection models, subsystem database/migrations, authorization-aware
     repository/service APIs, encrypted-secret integration, and runtime lifecycle
     wiring.
   - Add structured, redacted activity logging and explicit cache invalidation.
   - Add targeted isolation checks using at least two synthetic principals.
   - Keep production request resolution fixed to `local-user`; synthetic
     principals exist only to prove the backend boundary and future transition.
   - Define connection auth modes explicitly (none, encrypted bearer/header,
     and MCP OAuth); never persist raw headers or tokens in connection rows.

- **Chat tool-search vertical slice**
   - Declare the MCP/FastMCP and encryption dependencies directly.
   - Build filtered, prefixed, individually deferred MCP toolsets for current
     task authority and compose `ToolSearch` without changing built-in exposure.
   - Preserve MCP provenance through the existing global `PrepareTools` hook.
   - Mark `search_tools` replay-safe. Add an edge-case assertion that globally
     disabling every built-in tool does not let an MCP-only run use the no-tool
     stream-retry path; this is hardening rather than a primary integration seam.
   - Isolate unavailable connections during agent preflight so one enabled
     server cannot suppress built-ins and healthy MCP connections.
   - Wire initial chat, continuation, cancellation, output-cache, and recovery
     paths.
   - Prove MCP calls consume the existing tool-call budget and produce the same
     activity, retry, structured-failure, caching, and recovery contracts as
     built-in tools; add no MCP-specific limits or reporting surface.
   - Keep workflows, authored scripts, code execution, and delegate children
     disabled for MCP until their authority and effect boundaries are tested.

- **Management surface**
   - Add principal-scoped API models/endpoints and the basic connection UI in
     slice 6; extend that UI with OAuth-specific actions and states in slice 9.
   - Define sanitized connection-test and credential-presence contracts in slice
     6, then make connection tests operational through the transport manager in
     slice 7.
   - Ensure removal/disable closes active resources and affects subsequent runs
     without leaking state across principals.
   - Do not add principal IDs, owner selectors, user creation, or user switching
     to the frontend/API contract in this branch.

- **Explicit follow-up execution surfaces**
   - Evaluate delegate children, workflows, contexts, and authored direct-tool
     execution individually. Require explicit authority propagation and bounded
     tool budgets before enabling MCP on each surface.
   - Add stdio only after command allowlisting, environment filtering, working
     directory, process teardown, and deployment policy are specified.

- **Hardening and documentation**
   - Verify the transport slice's SSRF/egress policy, TLS rules, timeouts,
     response-size limits, concurrency limits, and redaction behavior end to end.
   - Document the current user-facing connection/tool-search contract and update
     architecture/ADR material without migration narrative.
   - Review dependency licenses/notices and container packaging.

## Validation Targets

Agents should add targeted scenarios and request maintainer-run full validation;
agents must not run `validation/run_validation.py`.

- An integration scenario with two principals proves connection definitions,
  credentials, status, tool discovery, and calls cannot cross owner boundaries.
- Provider/OAuth scenarios prove two synthetic principals can hold the same
  logical secret name without collision and that runtime lookup returns only the
  active principal's value. Product API scenarios continue to operate solely as
  `local-user` and expose no principal-management surface.
- Workflow scenarios prove API, scheduled, and tool-triggered runs retain the
  workflow owner's authority and resolve only that principal's secrets. System
  maintenance cannot read those values.
- A chat scenario proves built-in tools are present initially while MCP tool
  schemas are absent until `search_tools` discovers them, then proves the
  discovered tool can be called and replayed from persisted history.
- A provider-independent fallback scenario proves keyword discovery works with
  a model lacking native tool search.
- Failure scenarios cover unreachable/malformed servers, credential redaction,
  timeouts, cancellation, runtime shutdown, name collisions, oversized results,
  and tool-list changes.
- Recovery coverage proves MCP tools follow the existing tool recovery policy
  rather than a separate MCP-specific policy.
- API scenarios prove owner IDs cannot be injected and credential values are
  write-only.

Initial smoke target: a local test MCP HTTP server exposing one read-only tool,
called through a chat run only after tool discovery, with no external network or
real credential dependency.

## Contract-sensitive Areas

- New principal-owned persisted runtime state and database migrations.
- Replacement of `system/secrets.yaml`, migration of every existing secret
  consumer (including model API and OAuth state), encryption-key operations,
  principal-scoped caches, and secret redaction.
- Settings/reload and runtime shutdown behavior.
- Pydantic AI capability ordering and persisted tool-search history.
- Existing chat tool limits, recovery classification, and event payloads.
- API payloads, UI configuration forms, and removal semantics.
- Network egress and eventual local subprocess execution.

## Open Decisions Before Feature Development

The initial product-policy and integration-contract decisions are resolved. Any
new contract question discovered by the implementation probes must return to
Planning rather than being silently decided in code.

## Next Phase

Complete the focused contract probes and encrypted-secrets ADR, then move to
Feature Development beginning with encrypted secrets, followed by workflow
ownership, principal-owned MCP persistence/runtime composition, and the chat
tool-search vertical slice.

The later multi-user branch should be able to retain the database schemas and
domain services from this work. Its primary additions should be authentication,
principal resolution, user administration, frontend identity context, and an
explicit policy for system work that acts on behalf of a user—not a conversion
to multi-tenant storage.
