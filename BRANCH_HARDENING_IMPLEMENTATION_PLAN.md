# Branch Hardening Implementation Plan

## Objective

Finish the hardening of `dev/mcp-experimental` by closing the remaining MCP
network boundary, cross-database mutation, Google OAuth identity, legacy-secret,
and frontend OAuth lifecycle findings. Preserve the principal-owned connection
and encrypted-secret contracts without merging subsystem databases or exposing
secret material through APIs, logs, or durable mutation records.

The next workflow phase is **Feature Development**. Implement the stages below
in order, using targeted scenarios while iterating. Maintainers remain
responsible for the full validation suite.

## Existing Completed Hardening

- The branch diff and production Python quality baseline were reviewed.
- SQLite migration backups use SQLite's online backup API and pass an integrity
  check, including when committed data remains in WAL.
- Managed migrations run before MCP service construction.
- Google OAuth wrong-state callbacks do not consume valid pending attempts.
- Google connection deletion and disconnection validate ownership, include
  pending OAuth cleanup, and return consistent not-found errors.
- Google browser callback failures emit sanitized structured diagnostics.
- MCP connection tests preserve cancellation.
- Retained MCP clients repeat network-policy validation at request hooks as
  defense in depth. Socket-authoritative enforcement remains required below.

## Non-Negotiable Invariants

### Ownership and secrecy

- Connection metadata, credentials, OAuth state, mutation state, and runtime
  clients remain scoped to the captured `ExecutionAuthority` principal.
- Secrets, authorization codes, OAuth state values, tokens, client IDs, client
  secrets, raw mutation payloads, and credential-bearing URLs never enter API
  responses, activity logs, or `mcp.db` mutation records.
- Principal IDs remain internal persistence identities and are never accepted
  from normal connection API payloads.

### MCP network boundary

- Every new MCP or MCP OAuth TCP socket connects only to a numeric address from
  the exact DNS result that passed network policy for that connect attempt.
- The original hostname continues to control HTTP `Host`, connection-pool
  origin, TLS SNI, and certificate verification.
- A prohibited or mixed public/local resolution set causes rejection before any
  socket attempt. No fallback may resolve the hostname again behind policy.
- Local/private HTTPS remains allowed. Local/private HTTP requires an explicit
  acknowledgement on that connection; public HTTP is always rejected.
- Redirect following, Unix sockets, ambient proxies, and proxy environment
  inheritance remain disabled. Cancellation and standard timeout/error classes
  remain observable.

### Persistence and mutation

- ADR 0015 remains authoritative: `mcp.db` and `secrets.db` stay
  subsystem-owned files. Cross-database behavior uses an explicit durable saga,
  not SQLite `ATTACH`, a merged database, or assumed atomicity.
- A connection is runtime-eligible only when its lifecycle is `active` and it
  has no unresolved mutation.
- A successful mutation response means metadata, required secret effects,
  configuration version, runtime invalidation, and terminal logging have all
  settled.
- A crash at any mutation boundary leaves either the old active state or a
  durable idempotent operation that converges during reconciliation. It must not
  leave a partially credentialed connection active.
- Reconciliation applies each metadata/version transition at most once and
  preserves immutable connection IDs and slug reservations.

### Google OAuth lifecycle

- Google `client_id` is credential identity, not ordinary display metadata.
  Changing it immediately invalidates the previous secret, pending attempt,
  token grant, account identity, and capability readiness.
- Display name, default selection, and Gmail preference changes preserve OAuth
  readiness.
- Replacing a client secret invalidates the prior pending attempt and token even
  when the client ID is unchanged.
- Pending and token records are accepted only when bound to the current metadata
  generation and current client-secret identity. An `A -> B -> A` client-ID
  sequence cannot resurrect records from the first `A` generation.
- Legacy Google OAuth state is moved or deleted atomically inside `secrets.db`.
  A successful disconnect or delete cannot later reimport legacy credentials.

### Frontend lifecycle

- At most one OAuth poll owner exists per provider and connection ID.
- Restart, completion, disconnect, deletion, relevant configuration mutation,
  tab deactivation, and page teardown cancel owned timers and in-flight requests.
- A stale or aborted poll cannot reload cards, update feedback, or emit a
  configuration-changed notification.

## Architecture Decisions

### 1. Socket-authoritative MCP transport

Add an `MCPNetworkBackend` in `core/mcp/network.py` implementing
`httpcore.AsyncNetworkBackend`. Delegate normal I/O, TLS wrapping, and sleep to
`httpcore.AnyIOBackend`, but own `connect_tcp`:

1. Resolve and classify the original hostname once for the socket attempt.
2. Reject the complete result if it violates the existing address policy.
3. Pass only an approved numeric IP to the delegate backend.
4. If multiple approved addresses are supported, try only that captured set in
   deterministic order while respecting the remaining connect-timeout budget.
5. Reject Unix-domain socket connections explicitly.

Install the backend in a narrow HTTPX transport backed by
`httpcore.AsyncConnectionPool`. TLS remains above the network backend, so it
uses the original hostname automatically. Keep the request hook as
defense-in-depth for scheme, credentials, and OAuth-discovered endpoint checks.

Declare `httpcore>=1.0.9,<2` directly and bound HTTPX to
`httpx>=0.28.1,<0.29` in `pyproject.toml`, then update `uv.lock`. HTTPX 0.28 does
not expose a public network-backend parameter, so the narrow transport subclasses
`AsyncHTTPTransport` and installs its connection pool. These intentional
lower-level/version couplings must be protected by focused transport tests. Do
not adopt the prerelease HTTPX 1.0 or newly released `httpcore2` line in this pass.

Follow-up dependency trigger: when HTTPX publishes a stable release with public
async network-backend injection (upstream `encode/httpx#3749`), replace
`MCPAsyncHTTPTransport` with that API. Remove the `<0.29` bound only after the
existing numeric-address, SNI, streaming, exception, retained-client, and OAuth
transport scenarios pass against the public integration.

Rejected alternatives:

- Request-hook or TTL-based DNS validation still has a second resolution race.
- Rewriting request URLs to IP literals breaks origin, SNI, certificate, and
  pooling semantics.
- Process-wide `socket.getaddrinfo` patching is concurrency-unsafe.
- Replacing FastMCP transports is a larger contract change than installing a
  network backend beneath their HTTPX clients.

### 2. Atomic encrypted-secret primitives

Extend `EncryptedSecretsService` with typed, bounded operations that execute in
one `secrets.db` transaction:

- atomic batch deletion;
- atomic copy-preserving promotion of operation-scoped staged secrets to
  canonical identities, leaving staging evidence until MCP metadata is
  finalized;
- atomic exact-namespace deletion for principal-owned OAuth state;
- atomic relocation between namespace/name identities by decrypting with the
  source AAD, re-encrypting with destination AAD, authenticating the destination,
  and deleting the source before commit.

Keep OAuth storage-name hashing inside `EncryptedOAuthStorage`; expose narrow
move/delete-many helpers there rather than leaking hashed names into Google or
MCP services. Define destination-conflict behavior explicitly: preserve a valid
canonical destination and delete the stale legacy source, otherwise relocate
the source. Any authentication, encryption, verification, or injected failure
rolls back the entire operation.

### 3. Durable MCP mutation saga

Add managed MCP schema migration v3:

- `mcp_connections.lifecycle_state` with `active`, `pending`, and `deleting`;
- `mcp_connection_mutations` containing operation ID, owner, connection ID,
  mutation kind, validated non-secret desired metadata/action JSON, state,
  attempt count, timestamps, and a sanitized last error class;
- no plaintext credential, OAuth token, client secret, authorization state, or
  sensitive URL data in mutation rows.

Create an owning mutation coordinator inside `core/mcp/service.py` or a focused
`core/mcp/mutations.py`. It first registers durable staging cleanup, writes new
secret values under operation-scoped encrypted identities, commits intent and
lifecycle in `mcp.db`, applies one atomic secrets operation, finalizes
metadata/version/lifecycle in `mcp.db`, and then invalidates the retained runtime
client. A process death before intent therefore leaves a staging record that
reconciliation can remove without changing the prior connection state.

OAuth storage writes are lifecycle-fenced at persistence time. Every write must
prove that the owning connection is still `active` and has no unresolved
mutation; an OAuth adapter obtained before an update or deletion cannot recreate
state after the lifecycle boundary changes. Process-local locks and cancellation
remain useful coordination aids but are not the correctness mechanism.

The persistence fence is a random, non-credential token shared between the
active `mcp.db` row and an encrypted marker in `secrets.db`. An issued OAuth
adapter captures that token, and each OAuth write compares the marker and writes
in one `secrets.db` transaction. A mutation first makes the connection
non-active, then rotates the marker and clears OAuth state in one secret
transaction. Therefore a stale writer either commits before cleanup and is
removed, or observes the rotated marker and cannot commit afterward.

Reconciliation runs after managed migrations and secrets bootstrap but before
the MCP manager starts. Service mutation entry points also reconcile their
target before accepting another change. Reconciliation is bounded, idempotent,
and safe when invoked more than once. Rows with unresolved work never enter
runtime listings or manager acquisition. If reconciliation cannot progress,
leave the durable intent intact, log a sanitized retry failure, and report MCP
configuration/runtime as temporarily unavailable rather than activating partial
state.

Operation transitions:

- **Create with secrets:** register staging cleanup -> stage secrets -> insert
  pending connection and promote the record to intent atomically in `mcp.db` ->
  promote secrets -> mark active/remove intent -> notify. Recovery of a
  staging-only record removes staged values; failure after intent is recovered
  forward from the journal.
- **Metadata/auth-mode update:** write normalized desired metadata to the
  forward-only pending connection row without incrementing the version, record
  the non-secret action intent -> atomically delete obsolete credentials/OAuth
  state -> increment the version once and mark active/remove intent -> notify.
- **Set/replace credential or OAuth client secret:** register cleanup -> stage
  replacement -> record pending intent -> atomically promote replacement and remove invalid OAuth
  state where required -> increment version once -> activate/remove intent ->
  notify.
- **Clear credential:** record pending intent -> atomic delete -> increment once
  -> activate/remove intent -> notify.
- **Delete:** mark deleting and record intent -> atomically delete all connection
  secret namespaces -> delete connection row while retaining slug reservation ->
  remove intent -> notify.

Do not use optimistic cleanup ordering as the correctness mechanism. Best-effort
cleanup is permitted only for pre-intent staging artifacts; durable intents own
all post-intent recovery.

### 4. Google credential generation binding

Add managed connections migration v3 with
`oauth_generation INTEGER NOT NULL DEFAULT 1 CHECK (oauth_generation > 0)` and
include it in the internal `GoogleConnection` model. The metadata update
transaction increments it exactly once when the normalized client ID changes;
other edits preserve it.

Bind encrypted payloads as follows:

- client secret: `value`, `oauth_generation`, and a random `credential_id` that
  changes on every secret replacement;
- token state: current fields plus `oauth_generation` and `credential_id`;
- pending PKCE state: current fields plus `oauth_generation` and
  `credential_id`.

Resolution, status, OAuth start/completion, refresh, and Gmail availability must
verify both bindings before using state. Binding mismatch is authoritative
invalidation even if physical cleanup fails. Best-effort deletion may reduce
stale encrypted rows but is not required for correctness.

Legacy policy:

- An unbound legacy client secret may be bound to generation 1 on its first
  authenticated read.
- Unbound token and pending records are treated as stale and require
  reauthorization; silently binding them could preserve a grant created under
  a client ID changed by the current buggy implementation.
- Product documentation describes only the resulting current contract, not the
  migration history.

Use a composed Google domain operation for metadata updates so client-ID changes
can perform best-effort stale-record cleanup and emit one lifecycle event.
Correctness must still come from generation checks because lower-level service
callers and cleanup failures cannot be allowed to bypass invalidation.

Expected transitions:

- `ready` + preference/display/default edit -> `ready`.
- any state + changed client ID -> `not_configured`.
- any configured state + replacement client secret ->
  `authorization_required`.
- current secret + OAuth start -> bound pending attempt.
- callback with stale generation/credential -> reject before token exchange.
- valid completion -> `ready`.

### 5. Owned frontend OAuth polling

Replace detached recursive polling with provider-specific maps keyed by
connection ID. Each entry owns an `AbortController`, timer ID, deadline, and
unique generation token. Before and after every `await`, verify that the entry
is still the current owner. Poll by stable connection ID/endpoint rather than a
DOM node because card rendering replaces nodes.

Add cancellation helpers for one Google poll, one MCP poll, and all polls.
Cancel before save, manual completion, disconnect, delete, or restart. Cancel
all on `pagehide` and through an explicit configuration-tab deactivation hook;
wire that hook from the existing tab controller. Ignore `AbortError`. Terminal
connected/failed/expired outcomes remove ownership only if the finishing poll
still owns the map entry.

Give one-shot MCP status loading its own request generation/abort ownership so
an older render cannot apply results to replacement cards.

## Activity and Failure Events

Use existing subsystem logger tags. Stable event payloads contain operation and
connection identities, mutation kind/status, attempt count, and error class
only. They never contain secret values, raw mutation JSON, OAuth state, client
IDs, tokens, or unsanitized URLs.

- `mcp_connection_mutation_started`: `operation_id`, `connection_id`, `kind`,
  `status="pending"`.
- `mcp_connection_mutation_recovered`: the same keys plus `attempt_count` and
  `status="completed"`.
- `mcp_connection_mutation_completed`: operation/connection/kind and
  `status="completed"`.
- `mcp_connection_mutation_retry_failed`: operation/connection/kind,
  `status="pending"`, `attempt_count`, `error_type`.
- `google_oauth_identity_changed`: `connection_id`, `config_version`,
  `oauth_generation`, `status="invalidated"`.
- `google_legacy_oauth_state_migrated`: `connection_id`, `record_kind`, and
  bounded `record_count`.
- `google_legacy_oauth_cleanup_completed`: `connection_id`, bounded count, and
  `status="completed"`.

Avoid per-poll activity events; frontend polling is not a user-diagnostic
operation. Existing OAuth start/completion/failure events remain the lifecycle
record.

## Implementation Stages and Commit Boundaries

Progress:

- [x] Stage 1: authoritative MCP socket boundary.
- [x] Stage 2: atomic encrypted-secret operations and Google legacy cleanup.
- [x] Stage 3: Google credential identity lifecycle.
- [x] Stage 4: durable MCP mutation lifecycle.
- [x] Stage 5: frontend OAuth lifecycle ownership.
- [x] Stage 6: review and validation handoff.
- [x] Stage 7: atomic Google OAuth in-flight credential fencing and callback
  surface cleanup.
- [x] Stage 8: storage-level guard serialization and disconnect fencing.
- [x] Stage 9: Google deletion and grant-revision convergence.
- [x] Stage 10: durable Google deletion reconciliation and legacy-default fencing.
- [x] Stage 11: connection-scoped private HTTP acknowledgement.
- [x] Stage 12: third-pass adversarial concurrency and startup cleanup review.

### Stage 1: Authoritative MCP socket boundary

1. Refactor MCP URL resolution/classification into reusable host-policy helpers
   without changing the policy matrix.
2. Implement the network backend and HTTPX transport with a direct bounded
   `httpcore` dependency.
3. Wire the retained MCP and MCP OAuth client factories to the shared transport.
4. Add deterministic fake-backend tests and update the current MCP architecture
   contract.

Keep this commit independent from persistence changes.

### Stage 2: Atomic encrypted-secret operations and Google legacy cleanup

1. Add typed atomic batch-delete, promote, and relocate primitives.
2. Replace Google lazy get/put/delete migration with atomic relocation.
3. Make default disconnect/delete atomically cover scoped and legacy client
   secret, token, and pending identities.
4. Add concurrency, rollback, anti-resurrection, and principal-isolation tests.

### Stage 3: Google credential identity lifecycle

1. Add the managed schema migration and internal generation model.
2. Add generation/credential bindings and the conservative legacy policy.
3. Enforce bindings in status, start, completion, refresh, and Gmail capability
   availability.
4. Route API metadata updates through the composed lifecycle operation and add
   sanitized events.
5. Update current-contract settings/secrets and API/UI architecture docs.

### Stage 4: Durable MCP mutation lifecycle

1. Accept proposed ADR 0040 for the cross-database saga and add migration v3.
2. Implement typed mutation records, staging, reconciliation, and active-only
   runtime gating.
3. Fence OAuth persistence writes against the active lifecycle and unresolved
   mutation state, including adapters issued before a mutation begins.
4. Route create/update/credential/OAuth-secret/clear/OAuth-disconnect/delete
   operations through the coordinator one at a time.
5. Add failpoints at every durable boundary and prove restart convergence,
   exactly-once versioning, and slug retention.
6. Update MCP architecture and operational diagnostics documentation.

### Stage 5: Frontend OAuth lifecycle ownership

1. Implement Google and MCP poll-owner maps and cancellation helpers.
2. Wire mutation, tab deactivation, rerender, and page teardown cancellation.
3. Add request-generation ownership to one-shot status loading.
4. Add focused frontend tests for restart, stale response, mutation,
   deactivation, and terminal cleanup.

### Stage 6: Review and validation handoff

1. Run the targeted scenarios listed below.
2. Run `uv run ruff check .`, `uv run black --check .`, and
   `uv run mypy api core` with zero findings.
3. Run `npm run build:css` only if CSS inputs changed; polling JavaScript alone
   does not require it.
4. Review logs and persisted fixtures for secret leakage.
5. Move to Refactor and Hardening, then Commit and Review Prep.
6. Request maintainer results from the full validation suite before merge.

### Stage 7: Atomic Google OAuth in-flight credential fencing

1. Extend Google token persistence with an expected credential binding captured
   before the external OAuth request. In one secrets-store transaction, verify
   the authenticated client-secret payload still has the expected
   `oauth_generation` and `credential_id`, then persist the token grant. A
   changed or missing binding must reject the write without recreating token
   state cleared by a concurrent client-ID or client-secret mutation.
2. Carry the captured binding through authorization-code exchange, account
   identity lookup, and refresh. Do not rebind an external response to whatever
   credential happens to be current after an `await`.
3. Add deterministic interleaving assertions for client-secret replacement and
   client-ID replacement during token exchange, identity lookup, and refresh.
   Assert that the stale operation fails closed, the replacement credential
   remains authoritative, and no stale token state becomes loadable.
4. Remove the connection-ID-specific Google browser callback route. Keep the
   stable provider callback and manual per-connection completion API; pending
   cryptographic state remains responsible for resolving browser callbacks to
   the initiating connection.
5. Update current-contract API documentation if necessary, run the targeted
   Google scenarios and production Python quality gate, then request the
   maintainer-owned `integration/core` pre-merge profile.

### Stage 8: Storage-level serialization and disconnect fencing

1. Begin guarded secret mutations with an explicit SQLite write transaction
   before reading the encrypted guard, so the guard comparison and target
   mutation cannot be interleaved by another connection. Apply the same rule to
   guarded deletes.
2. Add an atomic OAuth-storage operation that replaces one non-expiring record
   while deleting related records in the same `secrets.db` transaction.
3. Make Google disconnect preserve the client-secret value and generation while
   rotating its internal credential identity and deleting pending/token state
   atomically. Reuse the operation for client-secret replacement.
4. Extend deterministic completion and refresh races to disconnect during token
   exchange, identity lookup, and refresh, plus storage-level concurrency
   coverage proving a competing guard writer cannot enter the compare/write
   window.
5. Repeat adversarial subagent review after targeted scenarios and the complete
   production Python quality gate pass.

### Stage 9: Google deletion and grant-revision convergence

1. Guard refresh persistence with both the exact credential identity and exact
   source token payload, so a stale refresh cannot overwrite a newer completed
   authorization.
2. Make disconnect credential rotation compare-and-swap the exact credential it
   observed and retry boundedly when another credential mutation wins.
3. Delete Google metadata before captured encrypted connection state, and make
   client-secret writes recheck metadata afterward with exact-value cleanup so
   a delete-versus-write interleaving cannot leave orphaned credentials.
4. Add deterministic refresh-versus-reauthorization,
   disconnect-versus-credential-mutation, and deletion-versus-secret-write
   scenarios, then repeat the adversarial review loop.

### Stage 10: Durable Google deletion reconciliation

1. Clear the captured default connection's shared legacy OAuth identities before
   promoting a replacement default, preventing lazy migration across connection
   identity during deletion.
2. Record a sanitized permanent Google deletion ledger in `connections.db` in the same
   transaction that removes metadata and promotes the replacement default.
3. Purge the deleted connection's exact encrypted namespace independently of
   live metadata. Retain immutable deleted IDs permanently, reconcile them at
   startup and on idempotent item-route retries, and remove the ambiguous legacy
   singleton delete route.
4. Make client-ID invalidation conditionally remove only the credential bound to
   the old generation, preserving a concurrently installed credential for the
   new generation.
5. Add injected cleanup-failure/retry coverage, default legacy replacement
   coverage, and client-ID-update-versus-new-secret coverage before another
   adversarial review round.

### Stage 11: Connection-scoped private HTTP acknowledgement

1. Replace the process-wide insecure-HTTP environment allowance with a disabled-
   by-default `allow_private_http` setting on each MCP connection.
2. Require that setting only for HTTP endpoints whose complete runtime DNS result
   is private; continue rejecting public HTTP, mixed public/private results, and
   prohibited address classes regardless of the setting.
3. Carry the setting through MCP client initialization, OAuth discovery and token
   exchange, durable mutation recovery, API projections, and the Connections UI.
4. Add migration and deterministic security coverage for Docker-style private
   service addresses, public HTTP rejection, and per-connection isolation.
5. Update installation and MCP architecture documentation, run targeted scenarios
   and the complete production Python quality gate, then request the maintainer-
   owned pre-merge profile.

### Stage 12: Third-pass adversarial concurrency and startup cleanup review

1. Reauthorize MCP clients against authoritative lifecycle, unresolved-mutation,
   configuration-version, and enabled state immediately before publication;
   serialize publication with invalidation epochs so an in-flight cold start cannot
   miss a concurrent mutation notification.
2. Bound MCP DNS resolution within the connect-timeout budget and atomically claim
   finalized mutation rows before terminal notification and logging side effects.
3. Bind legacy Google client-secret upgrades with exact-payload compare-and-swap,
   authoritative generation/deletion rechecks, and exact conditional cleanup.
4. Fence Google metadata cleanup and OAuth pending-state creation against concurrent
   credential, generation, disconnect, and deletion changes.
5. Clean up lifecycle-bearing services before re-raising configuration validation
   failures, preserving the public `RuntimeConfigError` contract.
6. Add deterministic interleaving scenarios for every finding, rerun the production
   Python quality gate, and request the maintainer-owned pre-merge profile.
7. Keep finalized MCP mutation evidence recoverable until serialized notification
   and terminal logging settle; make same-loop invalidation visible before client
   publication and drain cold-start connection work during shutdown.
8. Reauthorize legacy Google credential upgrades after compare-and-swap, consume
   pending OAuth attempts by exact payload and expiry, and retain one exact
   credential binding from pending validation through token persistence.

## Validation-First Targets

Add failing deterministic assertions before each implementation stage.

### MCP network policy

Extend `validation/scenarios/integration/core/mcp_connection_isolation.py` and
`validation/scenarios/integration/core/mcp_oauth_storage.py`:

- policy approves one IP and the delegate receives that numeric IP;
- DNS changes between request hook and socket connect, and the socket backend
  independently rejects the prohibited result without calling its delegate;
- mixed, forbidden, literal IPv4, and literal IPv6 cases retain their contract;
- allowed multi-address fallback attempts only captured approved addresses;
- TLS receives the original hostname for SNI while TCP receives the numeric IP;
- cancellation, DNS failure, and connect timeout preserve expected error types;
- both retained and OAuth factories install the policy backend.

### Atomic secrets and legacy Google state

Extend encrypted-secret security coverage and Google coordinator scenarios:

- failure after destination write but before source deletion rolls back both;
- destination conflict follows the defined canonical-wins rule;
- wrong-key/AAD authentication failure performs no mutation;
- concurrent move and disconnect cannot leave a legacy source able to reappear;
- disconnect/delete before or after lazy migration leaves neither scoped nor
  legacy token, secret, or pending state;
- another principal's identities remain untouched.

### Google generation binding

Extend `builtin_connection_configuration.py`,
`integration/core/google_oauth_coordinator.py`,
`integration/core/gmail_principal_connection.py`, and the relevant
API scenario:

- generation begins at 1, changes exactly once for a new client ID, and remains
  stable for equivalent ID or preference/display/default edits;
- a ready connection becomes `not_configured` immediately after ID change;
- no refresh or callback token exchange occurs with stale bindings;
- setting a new secret yields `authorization_required`; only a new grant yields
  `ready` and restores Gmail capability;
- replacing a secret invalidates pending/token records under the same client ID;
- `A -> B -> A` cannot resurrect old state;
- API responses expose no binding identifiers, prior account, or stale scopes;
- unbound client secrets follow the declared upgrade rule while unbound tokens
  and pending attempts are rejected.

### MCP mutation recovery

Add a dedicated persistence failure/recovery scenario and extend API assertions.
Inject failures:

- after secret staging but before intent;
- after intent commit;
- during atomic secret cleanup/promotion;
- after secret effects but before metadata finalization;
- after metadata finalization but before journal removal/notification;
- during delete and during concurrent duplicate reconciliation.
- an OAuth storage adapter issued while active attempts a write after the
  connection becomes pending or deleting and is rejected without recreating
  canonical OAuth state.

After service reconstruction, assert convergence, active-only runtime access,
one version increment, retained slug reservation, no orphan staging records,
no unresolved journal on success, idempotent retry, and absence of secret values
from `mcp.db`, API responses, and logs.

### Frontend poll ownership

Use the existing frontend test harness if available; otherwise add the smallest
focused JavaScript harness rather than asserting DOM/CSS through integration
scenarios:

- starting twice leaves one timer/request owner;
- save, completion, disconnect, delete, tab deactivation, and page teardown abort
  the owned poll;
- an aborted or superseded response cannot mutate feedback or reload cards;
- terminal status removes ownership;
- MCP rerender cannot strand a recursive poll;
- transient errors retry only while the same live owner remains and before its
  deadline.

## Documentation Impact

- Accept proposed ADR 0039 when the socket-authoritative MCP transport lands.
- Accept proposed ADR 0040 when the MCP cross-database mutation saga lands.
- Accept proposed ADR 0041 when Google credential-generation binding lands.
- Accept ADR 0045 for the restart-safe application-mediated OAuth flow shared
  by MCP and native integrations.
- Update `docs/architecture/mcp-connections.md` for socket-authoritative address
  enforcement, active-only mutation lifecycle, and reconciliation.
- Update `docs/architecture/settings-secrets.md` for atomic internal secret
  relocation and generation-bound Google OAuth state.
- Update `docs/architecture/api-ui.md` for current OAuth readiness and polling
  ownership behavior.
- Keep product docs limited to the current resulting contract; do not include
  migration tutorials or comparisons with the old behavior.

## Assumptions and Deliberate Limits

- AssistantMD continues to run its MCP clients on the asyncio/AnyIO backend;
  adding Trio support is outside this hardening scope.
- Local/private HTTPS remains a supported MCP target; this plan fixes address
  authority without changing the existing policy matrix.
- The MCP mutation journal contains only non-secret desired metadata and action
  kinds. Secret replacement values exist only in operation-scoped encrypted
  records in `secrets.db`.
- Unresolved mutations are recoverable runtime state, not permission to expose
  partially applied configuration.
- Dependency refresh beyond the direct bounded `httpcore` declaration is a
  separate effort unless implementation exposes a relevant security advisory.
