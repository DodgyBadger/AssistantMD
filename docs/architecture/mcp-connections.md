# MCP Connections

AssistantMD consumes MCP servers as a second-class tool source. It does not
expose an MCP server. Connection management is principal-owned even though the
current product resolves every interactive request as its single local user.

## Persisted connection contract

Sanitized connection definitions live in `system/mcp.db`. Each connection has:

- an immutable connection ID and immutable model-facing slug;
- an owner principal recorded in the database but not exposed in the API/UI;
- a display name, enabled state, and Streamable HTTP, SSE, or fixed-companion
  stdio transport;
- an optional exact-name tool allowlist;
- an explicit auth mode and, for custom-header auth, a non-secret header name;
- a monotonically increasing configuration version for runtime invalidation.

Connections also have an internal mutation lifecycle. Only connections in the
`active` lifecycle with no unresolved mutation are visible to runtime clients.
Creates, updates, credential changes, and deletion use a durable mutation intent
while coordinating `mcp.db` with the separately owned encrypted secrets store.
Startup reconciles incomplete intents before the MCP manager starts. A failed
operation remains unavailable and retryable rather than exposing partially
applied metadata or credentials.

Slug reservations survive connection deletion, so a model-facing prefix is
never reassigned to a different server and persisted tool history cannot drift.

Connection URLs cannot contain user-info, query parameters, or fragments.
Static bearer/header values are encrypted in the principal-owned secrets store
under the immutable connection ID. API responses expose credential presence but
never credential values.

The owner is derived from execution authority. Normal request payloads cannot
select an owner, and lookup/update/delete operations scope their database query
by both owner and connection ID so a foreign identifier is indistinguishable
from an absent one.

Companion stdio connections have no URL or credential fields. They persist an
absolute executable, literal ordered arguments, working directory, bounded
non-secret environment, and optional companion-path MCP Roots. Creation,
updates, testing, and runtime acquisition require advanced execution mode. The
transport always uses deployment-owned SSH coordinates and a versioned
structured forced-command envelope; connection metadata cannot select another
host, user, key, or shell command.

## Current management surface

The System tab can create, edit, enable, disable, and delete connections; select
HTTP, SSE, or companion stdio; set an allowlist; and set or clear applicable
bearer/custom-header credentials. Strict YAML/JSON import normalizes companion
stdio configuration into the ordinary create contract. Enabling a connection
trusts the tools allowed by its policy:
AssistantMD does not infer whether remote tools are read-only or mutating.

The runtime owns lazy, principal-scoped MCP clients keyed by connection ID and
configuration version. Concurrent cold requests share initialization, while
configuration and credential changes invalidate the affected client. Active
catalog leases freeze tool definitions for one execution boundary; idle clients
and all shutdown resources close within bounded cleanup paths. Application
startup does not connect to configured servers.

The UI connection test uses this retained manager and lists the effective
allowed tools. Results distinguish readiness, authentication failure, timeout,
unreachable servers, network-policy rejection, and MCP initialization failure
without returning credentials or raw transport errors.

Companion stdio clients are retained by the same manager. MCP framing crosses a
local OpenSSH process while the provider runs in the companion. Raw SSH/provider
stderr is discarded. Roots are advertised during initialization. Invalidating,
evicting, cancelling, or shutting down the client closes SSH; the companion
forced-command wrapper then owns cleanup of the provider's complete process
tree. Server instructions, prompts, and resources remain excluded from chat.

Remote endpoints require HTTPS. Plain HTTP is accepted only for local/private
addresses when that connection explicitly enables `allow_private_http`.
Retained and OAuth MCP clients repeat URL network-policy checks immediately
before every outbound request. A
socket-level network backend resolves each new connection, rejects the complete
address set unless it satisfies policy, and gives the operating system only an
approved numeric address. HTTP origin, `Host`, TLS SNI, and certificate checks
continue to use the configured hostname. Clients ignore ambient HTTP proxy
configuration and do not follow redirects.

### HTTP transport dependency boundary

HTTPX 0.28 does not expose its httpcore network-backend injection through the
public `AsyncHTTPTransport` constructor. `MCPAsyncHTTPTransport` is therefore a
version-bounded adapter that installs an `AsyncConnectionPool` using HTTPX's
private `_pool` integration point. `pyproject.toml` bounds HTTPX below 0.29 and
declares httpcore 1.x directly so dependency resolution cannot silently change
that boundary.

Replace this adapter when a stable HTTPX release provides public async
network-backend injection. The replacement must retain the socket-authority,
numeric-address, HTTP origin, TLS SNI, streaming cleanup, exception mapping, and
OAuth transport assertions before the HTTPX upper bound is removed. Upstream
tracking: `encode/httpx#3749`.

## Chat tool contract

Each primary chat run waits for a settled snapshot of the current principal's
enabled MCP connections before its first model request. An unavailable server
does not block built-in tools or healthy MCP servers; the run receives a
sanitized availability note and emits a task warning event.

MCP tools use immutable connection-slug prefixes and are absent from the initial
tool schemas. Pydantic AI's tool search discovers matching tools on demand. Once
discovered, MCP calls use the normal chat tool-call budget, activity events,
oversized-output handling, failure reporting, cancellation, and conservative
recovery behavior. Server instructions are not added to the chat prompt.

Catalog definitions remain frozen for the run. Connection changes invalidate
the retained client for subsequent runs without changing a run already in
progress. Runtime leases are released when preflight fails, task startup fails,
or the chat finishes or is cancelled.

## OAuth connection flow

OAuth connections are initiated explicitly from the System tab. AssistantMD
returns the authorization URL to the frontend and never launches a browser from
the backend, so the same flow works when the application is hosted headlessly.
The normal callback can complete automatically when the AssistantMD URL is
reachable; otherwise the user can paste the redirected URL into the connection
card.

When `ASSISTANTMD_PUBLIC_URL` is configured, its normalized origin is
authoritative for MCP callback construction even if the browser or reverse
proxy reports a different host. The connection API and UI expose the resolved
callback URI and identify its source without exposing OAuth state. When the
setting is absent, an interactive start may supply a browser-derived callback
only when its path exactly matches the owned connection callback route. The UI
warns when its current origin differs from the configured callback origin.

OAuth discovery follows protected-resource and authorization-server metadata
before MCP initialization. Servers may use dynamic client registration or a
pre-registered client ID and encrypted client secret. Optional configured
scopes override metadata scope selection. These are capability branches, not
provider-named pathways.

OAuth tokens and dynamic client-registration state use the encrypted,
principal-and-connection-scoped secrets store. Chat and connection tests may use
and refresh an existing token, but they cannot initiate interactive
authorization. Disconnecting, deleting, or changing a connection away from
OAuth clears its stored OAuth state. Short-lived PKCE completion state is also
encrypted, allowing a callback or pasted redirect to complete after an
AssistantMD restart until the attempt expires.

Each active connection has an OAuth persistence fence shared with an encrypted
marker. OAuth storage writes verify that marker in the same secrets transaction
that stores the value. OAuth-sensitive reconfiguration and deletion rotate the
marker while clearing the namespace, preventing an adapter issued before the
lifecycle change from recreating cleared authorization state.
