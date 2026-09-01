# AssistantMD Owner Authentication Implementation Plan

## Status

Implementation in progress. The first foundation increment is implemented:

- typed `disabled`, `loopback`, `trusted_proxy`, and `owner_token` policy modes;
- explicit mode selection with fail-closed configuration validation;
- file-backed or development environment secret loading with bounded, redacted
  secret material;
- exact immediate-peer loopback admission;
- constant-time proxy assertion and owner-bearer verification;
- optional strict trusted-proxy network validation; and
- domain-separated owner-session key derivation;
- compact stateless owner sessions containing only signed, bounded claims;
- strict signature, schema, issuance-time, expiry, and rotation validation; and
- per-session CSRF proofs stored only as a signed digest;
- pure ASGI enforcement covering HTTP and WebSocket scopes before routing;
- exact public method/path classification with unclassified routes denied by
  default in authenticated modes;
- duplicate/malformed credential-header rejection and forwarded-header-immune
  loopback checks; and
- CSRF enforcement for mutating owner-session requests while owner bearer calls
  remain non-ambient programmatic authentication.

The shared application composition root, browser owner-session exchange, and
live request enforcement are now implemented. Production requires an explicit
mode; `scripts/dev run` selects loopback only when bound to loopback, the
production Compose example now selects disabled mode for its deliberately
unprotected host-loopback-published local deployment, and validation selects
disabled mode explicitly. The image continues listening on `0.0.0.0`: a request
forwarded through a Docker bridge does not have a loopback immediate peer inside
the container, so application `loopback` mode is not presented as a standard
bridged-container option. Production configuration does not add a second
bind-address environment variable.

Owner-token live adversarial review found no authentication or CSRF bypass.
Hardening from that review now rejects duplicate JSON credential keys,
duplicate security cookies, mixed bearer/session credentials, aggregate headers
over 64 KiB, and disconnected credential bodies without an unhandled error.
Failed authentication uses a bounded process-local per-peer sliding window (10
failures per 60 seconds) and returns `429` with `Retry-After: 60`. Production
ingress must enforce its own header ceiling because the ASGI server allocates
headers before application middleware can reject them.

Owner sessions remain intentionally stateless. Logout deterministically expires
the browser cookies but cannot revoke a previously copied signed cookie; it
remains valid until its 12-hour expiry or owner-token rotation. Server-side
session revocation is deferred unless the product later requires stolen-session
invalidation.

This plan defines a standalone AssistantMD change. Advanced shell access depends
on this boundary, but authentication is useful independently and must be
implemented and validated before the shell capability is composed into chat.

## Objective

Provide configurable ingress authentication that, when enabled, requires proof
of installation ownership before a caller can use AssistantMD's web UI or
application interfaces. Network reachability alone grants no access in an
authenticated mode. An explicitly selected disabled mode preserves completely
open access for recovery and experimentation without weakening the behavior of
the authenticated modes.

The initial product remains single-user. A configured ingress authenticator
authenticates the caller as the installation's fixed interactive principal,
`local-user`. Authentication and principal authority remain separate concepts
so a future multiuser authenticator can resolve a different principal without
changing the downstream execution-authority model.

## Current Implementation Analysis

### Application boundary

- `main.py` creates one FastAPI application, includes `api.endpoints.router`,
  mounts `/static`, serves `/`, exposes the framework OpenAPI/docs routes, and
  installs response-cache and observability middleware.
- `api.endpoints.router` owns the `/api` surface and globally depends on
  `use_request_authority`.
- `api.principal.resolve_request_principal()` currently performs no
  authentication and always returns `LOCAL_USER_PRINCIPAL`.
- The root page, static mount, OpenAPI schema, and generated documentation are
  outside the API router dependency. Protecting only the router would therefore
  leave important application surfaces unclassified.
- The API includes normal JSON requests, multipart uploads, file downloads,
  HTML OAuth callbacks, and an SSE chat-task event stream. The frontend uses
  native `fetch` and `EventSource`; there is no single authenticated request
  adapter today.
- There is currently no WebSocket endpoint, but the boundary must fail closed
  for future WebSocket routes rather than relying on HTTP-only assumptions.

### Identity and asynchronous work

- `ExecutionAuthority` contains a stable `principal_id`, and request authority
  is installed in a context variable for the complete API dependency scope.
- Chat, ingestion, connection, MCP, secrets, workflow, and execution-task
  services already capture or require authority at important boundaries.
- Durable chat and task records carry principal ownership beyond the originating
  request. The owner credential must never be copied into these records; only
  the resolved principal may propagate.
- ADR 0028 establishes explicit execution principals. ADRs 0034, 0035, and 0038
  establish principal ownership for secrets and connections. Owner
  authentication should feed these contracts rather than create a parallel
  authorization system.

### OAuth and public origin

- Google and MCP OAuth callbacks currently live under the globally
  principal-resolving API router. Their endpoints validate random pending OAuth
  state inside the service only after request authority has already been
  installed as `local-user`.
- OpenAI supports callback, manual, and device flows with distinct redirect
  behavior. Each flow must be inventoried rather than covered by a blanket
  callback exemption.
- ADR 0036 makes the canonical public origin authoritative for externally
  reachable callbacks. Owner authentication must preserve that URL contract.
- OAuth state is already a high-entropy, time-bounded correlation mechanism in
  the shared OAuth flow. Callback authentication must resolve the principal
  bound to that pending state before installing execution authority, and must
  consume or invalidate state according to the existing generation rules.

### Configuration, deployment, and validation

- Infrastructure settings are environment-driven through `AppSettings`; the
  protected system root is persistent runtime state, and encrypted application
  secrets are principal-owned.
- Production Compose currently binds port 8000 to loopback by default and uses
  `/app/system` for persistent system state. Loopback binding is defense in
  depth, not authentication.
- The validation harness constructs a smaller FastAPI application directly from
  `api_router`, and its shared API client sends no authentication. Both must be
  updated or validation would exercise a different boundary than production.
- `validation/scenarios/integration/core/api_endpoints.py` is the existing
  comprehensive endpoint scenario. It should remain the broad authenticated
  regression target, while a dedicated authentication scenario owns adversarial
  boundary assertions.

## Security and User Experience Contract

### Authentication modes

AssistantMD supports alternative ingress authentication modes. A deployment
selects one mode; they are not cumulative challenges.

**Disabled** preserves the current unprotected behavior for recovery, local
testing, and deliberate experimentation:

- no request authentication is performed for the UI, API, streams, uploads,
  downloads, generated documentation, or OAuth callbacks;
- every network peer that can reach AssistantMD can use the complete exposed
  application surface and resolves to the fixed `local-user` principal;
- this explicitly includes the advanced-shell container, which may call and
  control AssistantMD through its API if network routing permits;
- no endpoint-by-endpoint residual authentication is retained in this mode; and
- startup and the System UI display a prominent persistent warning, but do not
  prevent advanced mode or otherwise override the operator's choice.

Disabled mode must be selected explicitly. Missing, invalid, or incomplete auth
configuration must never fall back to it. Product documentation labels it
unprotected and not recommended for network-accessible deployments, without
presenting Docker binding, a firewall, or user intent as equivalent to
application authentication.

**Loopback** is the seamless mode for a conventional local deployment:

- AssistantMD performs no interactive login and accepts a request only when the
  immediate socket peer is exactly `127.0.0.1` or `::1`;
- forwarded headers never influence this decision, and configurable trusted
  networks are not supported in this mode;
- the deployment binds the published port to host loopback rather than all host
  interfaces;
- Docker bridge peers, including the advanced shell, are not loopback and are
  rejected even if they can route to the AssistantMD service; and
- host-network deployment is unsupported because it can make the peer boundary
  ambiguous.

Loopback mode trusts processes already running on the local host and makes no
claim against malicious software operating with that host access. It protects
against remote and advanced shell peers without creating a browser credential.

**Trusted proxy assertion** is recommended when Caddy, Tinyauth, Authelia,
Authentik, or another ingress already authenticates the human user:

- the proxy removes any client-supplied assertion header and injects a
  cryptographically random shared assertion into the upstream request;
- AssistantMD verifies the assertion in constant time and, where configured,
  also requires the immediate network peer to match an explicit trusted-proxy
  address or network;
- the shared assertion is deployment infrastructure state, not a human
  password, and is never exposed to the browser;
- normal UI requests, `fetch`, SSE, uploads, downloads, and browser callbacks
  traverse the authenticated proxy without a second AssistantMD login; and
- direct requests from the advanced shell, other Compose services, the LAN, or the
  host fail because they neither traverse the trusted proxy nor possess its
  assertion.

The proxy must overwrite the assertion header rather than append to or preserve
an inbound value. Trusting identity-style headers such as `X-Forwarded-User`
without a secret assertion and verified immediate ingress is insufficient.

**Owner-token session** is the fallback for deployments without an
authenticating proxy and for direct programmatic access:

- the browser exchanges a cryptographically random owner token for an HttpOnly
  AssistantMD session; or
- a programmatic caller supplies the owner token as a bearer credential.

The selected mode and its credentials are configured at deployment time. The
mode cannot be changed through the System settings API, preventing an
application request from weakening its own ingress boundary. In disabled mode,
operators change deployment configuration and restart to restore protection.

### Installation credentials

- The trusted-proxy assertion and fallback owner token are provisioned outside
  AssistantMD's user-editable settings and principal-owned secret APIs.
- Production accepts the active mode's secret from a root-owned/Docker secret
  file. A direct environment variable may be supported explicitly for local
  development, with deployment documentation preferring the file-based source.
- Startup fails closed when an authenticated mode or its required secret is absent,
  empty, malformed, too short, or loaded from an unsupported source.
  AssistantMD never silently generates a replacement that could lock an
  operator out after restart.
- Secret comparison is constant-time. Rotation is a deployment operation;
  owner-token rotation immediately invalidates browser sessions derived from
  the previous token.
- Neither raw secret is ever returned by an API, rendered in HTML, stored in
  browser-readable storage, placed in a URL, or written to logs, traces,
  activity, errors, validation artifacts, or diagnostics.

### Browser experience without an authenticating proxy

1. An unauthenticated browser receives a minimal sign-in page that does not need
   protected static assets.
2. The browser submits the owner token once to a bounded session-exchange
   endpoint over the configured origin.
3. AssistantMD verifies the token and returns a short-lived, renewable,
   `HttpOnly` session cookie containing no owner credential.
4. The normal UI, static assets, APIs, downloads, and SSE stream become
   available through that cookie.
5. Sign-out clears the session. Expiry or token rotation returns the user to the
   sign-in page without exposing whether a supplied token was close to valid.

Cookie policy is `HttpOnly`, `SameSite=Lax` or stricter, a narrow path, and
`Secure` for HTTPS deployments. The implementation must define an explicit
loopback-development exception; it must not silently weaken cookies for a
non-loopback HTTP public origin.

Cookie-authenticated state-changing requests require CSRF protection in
addition to SameSite and origin checks. A per-session CSRF value may be readable
by first-party JavaScript because it is not installation authority. Frontend
requests should go through one small request helper that adds the CSRF header,
normalizes authentication expiry, and preserves existing response behavior.
Native `EventSource` continues to use the session cookie and needs no token in
its URL.

In trusted-proxy mode this AssistantMD sign-in and session exchange are disabled.
The upstream authentication session is the only human-facing login. CSRF and
origin protection still apply to state-changing requests because the upstream
proxy's browser session is ambient authority; AssistantMD may validate a
first-party CSRF value without creating a second authentication session.

### Programmatic and server-owned requests

- In owner-token mode, a caller may authenticate directly with the owner token
  in the `Authorization: Bearer` header. Query-string and request-body
  credentials are rejected.
- In trusted-proxy mode, programmatic clients use the authenticating proxy's
  supported client flow. Direct owner-bearer access is disabled unless a future
  explicit multi-auth mode is separately designed and reviewed.
- Direct bearer requests do not require browser CSRF handling because they do
  not rely on ambient cookie authority.
- In-process AssistantMD work should call Python services directly. If a
  server-owned HTTP transport is genuinely required, it may attach the owner
  credential only to a fixed local AssistantMD destination.
- No generic fetcher, redirect follower, browser tool, webhook, proxy, MCP
  client, model-selected URL, or shell command may receive an authenticated
  transport. Redirects from authenticated internal requests must be rejected or
  independently re-authorized to prevent a confused deputy.

### Default-deny route classification

The authentication boundary wraps the complete ASGI application so it covers
HTTP routes, mounted applications, streaming responses, and future WebSockets.
Every reachable surface is protected unless it appears in a small typed public
classification with its permitted methods and response contract.

When authentication mode is explicitly disabled, the boundary records that
state and admits every surface. Route classification remains testable so
switching the same deployment to an authenticated mode protects the complete
inventory without relying on individual endpoint changes.

Initial public candidates are limited to:

- a bounded liveness/readiness endpoint that reveals no configuration or
  runtime inventory;
- the minimal sign-in page and session-exchange endpoint when owner-token mode
  is active; and
- OAuth callback endpoints whose one-time pending state authenticates and
  resolves the bound principal before any authority-dependent service runs.

OpenAPI JSON and generated API documentation are authenticated. Static assets
are authenticated except any deliberately isolated asset required by the
minimal sign-in page. CORS is not an authentication mechanism and remains
closed unless a separate requirement establishes an allowlist.

An automated route inventory must fail when a new route or mount lacks an
explicit protected or public classification. Public classification is reviewed
as a security-sensitive code change, not inferred from path prefixes alone.

### Principal integration

Authentication produces a transport-level authenticated identity. A resolver
maps that identity to a `Principal`; initially both a verified proxy assertion
and a verified owner credential map to `LOCAL_USER_PRINCIPAL`.
`use_request_authority` then installs
`ExecutionAuthority.from_principal(principal)` exactly as downstream services
expect.

The proxy assertion, owner token, session cookie, CSRF value, and OAuth state
are never an `ExecutionAuthority` and never become tool arguments, model
dependencies, chat metadata, task snapshots, or resource ownership keys.
Authentication failure must occur before principal resolution. Request
authority must reset after normal responses, streaming completion, disconnects,
exceptions, and cancellation.

This seam preserves a future multiuser path: another authenticator can resolve
distinct principals while the existing principal-owned services and advanced shell
tenancy resolver continue to enforce authorization.

## Token Non-Disclosure Invariants

Use unique sentinel proxy and owner credentials during validation and prove they
are absent from:

- HTML, JavaScript, URLs, cookies, API payloads, OpenAPI output, and response
  headers other than the caller-supplied request authorization header;
- prompts, chat history, summaries, context templates, Pydantic AI dependencies,
  tool disclosure, tool calls, and tool results;
- vaults, caches, task/session snapshots, workflow state, imports, and exports;
- system settings responses, connection metadata, virtual documents, logs,
  activity events, traces, exception messages, and validation artifacts; and
- child-process environments, command lines, the advanced shell filesystem,
  advanced shell environment, shell stdin/stdout/stderr, and mounted volumes.

Secret-bearing request headers must be redacted before observability middleware
can record them. Authentication errors use fixed, non-reflective messages and
must not include submitted values.

## Implementation Slices

### Slice 1: Authentication primitives and configuration

- Add a focused authentication package containing mode selection, credential
  loading, exact immediate-peer loopback verification, proxy-assertion
  verification, owner-token verification, constant-time comparison, session
  issuance/verification, CSRF verification, redaction helpers, and typed
  authenticated identity.
- Add mutually exclusive trusted-proxy and owner-token production inputs, plus
  deliberate development inputs, to infrastructure settings without exposing
  their values through the System settings API.
- Validate the immediate peer before honoring a proxy assertion when a trusted
  peer allowlist is configured, with proxy/header parsing that cannot be
  influenced through forwarded client headers.
- Implement disabled mode as an explicit top-level policy result, with no secret
  loading and no partial endpoint protection. Emit one startup warning and
  expose a sanitized warning state for persistent display in the System UI.
- Define session lifetime, cookie name, token minimum entropy/encoding, rotation
  behavior, trusted-origin checks, and bounded authentication-request size.
- Add process-local, bounded authentication-failure throttling keyed without
  persisting submitted credentials. Document that reverse-proxy rate limiting
  remains useful defense in depth.
- Unit-test parsing, comparison, expiry, rotation, CSRF, origin rules, malformed
  inputs, and redaction.

### Slice 2: Complete application boundary and browser session

- Refactor application construction into one composition root used by
  production and validation so mounts, middleware, route classification,
  exception handlers, and auth behavior cannot drift.
- Install default-deny ASGI authentication ahead of route execution and ensure
  observability receives redacted request metadata.
- Add mode-aware browser handling: seamless asserted access in trusted-proxy
  mode, minimal sign-in/session/sign-out surfaces in owner-token mode, and
  current open access in disabled mode. Authenticated modes protect `/`,
  `/static`, `/api`, OpenAPI, and docs.
- Introduce a centralized frontend request helper and migrate existing `fetch`
  calls to it; preserve native cookie-authenticated SSE reconnect semantics.
- Return machine-appropriate `401` responses for APIs/streams and a sign-in
  navigation for browser document requests without redirect loops.
- Prove streaming and file responses retain authority for their full lifetime
  and reset it afterward.

### Slice 3: Principal and OAuth callback integration

- Change request-principal resolution to require an authenticated identity and
  map the owner identity to `LOCAL_USER_PRINCIPAL`.
- Separate callback routes from the unconditional API-router authority
  dependency. Validate and consume pending OAuth state, recover its bound
  principal, then install authority for completion.
- Audit Google, MCP, OpenAI browser, OpenAI manual, and OpenAI device flows
  individually, including expiry, replay, wrong-generation state, callback
  errors, and canonical public-origin behavior.
- Confirm background tasks capture only principal authority and never transport
  credentials.

### Slice 4: Deployment, migration of validation clients, and hardening

- Add both trusted-proxy assertion and owner-token secret-file wiring examples
  to deployment documentation and development startup tooling. Include a Caddy
  example that strips the inbound assertion header before setting the upstream
  value, keeps the secret out of browser responses, and prevents the advanced shell
  from reading it. Document generation, rotation, recovery, reverse-proxy TLS,
  trusted-peer configuration, and the loopback-only development exception.
- Keep the production image listening on `0.0.0.0`; container reachability is
  controlled by Compose networking and published-port bindings rather than an
  application bind-address environment variable. Do not duplicate the
  development launcher's `--address` override in production configuration.
- Remove `loopback` from the bridged-container Compose example because Docker
  forwarding does not preserve an actual loopback socket peer. Use `disabled`
  only for an explicitly unprotected, host-loopback-published local example,
  and provide `owner_token` and `trusted_proxy` as the authenticated production
  choices. Document that application `loopback` mode is limited to direct
  process or compatible host-network deployments where AssistantMD observes an
  actual loopback peer.
- Document disabled mode for recovery and deliberate testing, including an
  example showing that the UI and API are open to the host, LAN, advanced shell, and
  any other routable peer. Do not describe it as a containment boundary.
- Teach the validation controller and API client to provision a per-run sentinel
  credential and authenticate all protected calls. Keep public health checks
  explicitly unauthenticated.
- Add route/mount inventory assertions and credential-leak artifact scanning.
- Add a live advanced shell probe proving that every sensitive AssistantMD surface
  rejects unauthenticated requests while normal browser and bearer paths work.
- Review response headers, CORS, proxy forwarding, host/origin validation,
  request-size limits, failure throttling, and authenticated redirect behavior.

## Validation Targets

Create a dedicated integration scenario, proposed as
`validation/scenarios/integration/core/api_owner_authentication.py`, with
artifacts that demonstrate:

- unauthenticated access is denied for UI, static, OpenAPI/docs, representative
  reads and mutations, uploads, downloads, SSE, and an ASGI WebSocket probe;
- the explicit public health contract works before and after runtime bootstrap
  and reveals only its bounded schema;
- correct proxy assertion and owner bearer authentication succeed in their
  respective modes; missing, spoofed, malformed, duplicate, body/query,
  expired, rotated, and incorrect credentials fail uniformly;
- trusted-proxy mode does not display an AssistantMD login, rejects assertions
  from an untrusted immediate peer when peer restrictions are enabled, and
  ignores spoofed forwarded-source headers;
- disabled mode admits unauthenticated UI, API, streaming, file, docs, OAuth,
  and advanced-shell-originated requests, displays its warning, and never activates
  because another mode is merely misconfigured;
- loopback mode admits actual IPv4 and IPv6 loopback peers without login while
  rejecting Docker, LAN, malformed, and forwarded-header-spoofed peers;
- browser exchange creates a token-free HttpOnly cookie, CSRF is required for
  mutations, sign-out/expiry work, and cross-origin requests fail;
- OAuth callbacks succeed only for valid pending state bound to the correct
  principal and reject replay, expiry, substitution, and wrong-generation
  state;
- authenticated SSE survives reconnect and cannot leak authority after stream
  completion or disconnect;
- the route inventory rejects an intentionally unclassified test route and
  accounts for mounts and framework-generated routes;
- an authenticated request installs `local-user` authority, while an
  unauthenticated request installs none; and
- sentinel scanning proves the owner credential never reaches any model,
  persisted artifact, response, diagnostic, or advanced-shell-visible location.

Extend `validation/scenarios/integration/core/api_endpoints.py` so its existing
full endpoint inventory runs through the authenticated shared client. Extend
the existing principal-authority validation with request-authentication and
context-reset assertions. Maintainers run the full validation suite; agents run
targeted checks and request the maintainer-owned full result.

Before handoff, run the repository's production Python quality gate (Ruff,
Black, and MyPy for `api` and `core`) plus targeted authentication tests. Run
`npm run build:css` only if the sign-in UI changes the stylesheet source.

## Contract-Sensitive Areas

- All HTTP, mounted-static, SSE, future WebSocket, upload, download, docs, and
  OAuth callback routing.
- Cookie, CSRF, origin, redirect, proxy, and public-origin behavior.
- Infrastructure settings and production secret-file deployment.
- Persistent sessions only if the selected session design stores server-side
  state; the preferred initial design is stateless, signed, short-lived sessions
  so no authentication database migration is required.
- Validation API-client behavior and artifacts.
- Principal resolution and execution-authority lifetime.
- Logs, traces, activity events, exception serialization, and secret redaction.

## Explicitly Out of Scope

- Multiple owner accounts, passwords, password reset, invitations, roles, or an
  identity-provider UI.
- Multiuser principal provisioning or changing principal-owned persistence.
- Passing AssistantMD authority into the advanced shell container.
- Using the encrypted connection-secret APIs as a second owner-credential
  store.
- General CORS enablement or remote browser access over insecure HTTP.
- Advanced shell tool composition, stdio MCP connections, and advanced shell
  provisioning; those remain in the advanced-mode plan.

## Implementation Decisions to Confirm During Slice 1

- Exact mode, secret-file, assertion-header, and trusted-peer setting names plus
  the deliberately development-only direct environment fallbacks.
- Signed-session format and lifetime. Prefer a stateless session whose signing
  key is domain-separated from the owner token so rotation invalidates it
  without storing another credential.
- Exact public health schema and whether liveness and readiness should be split.
- Whether generated docs remain enabled and protected in production or are
  disabled there entirely.
- The narrow loopback HTTP cookie policy for `scripts/dev run`.

These choices do not change the boundary: default deny, credential
non-disclosure, explicit public classification, CSRF protection for ambient
browser authority, no duplicate human login in trusted-proxy mode, and
separation from principal authority are required invariants.

Those security invariants apply to authenticated modes. Disabled mode is an
explicit opt-out from the authentication boundary and makes no API-access
security claim.

## Next Phase

Proceed to Feature Development for the remaining Slice 4 deployment correction:
update the production Compose example and installation/security documentation,
then verify the rendered Compose configuration and use a focused bridged-network
probe to demonstrate why `loopback` is not a valid container default. Maintainers
retain ownership of the full validation profile.
