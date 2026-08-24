# MCP Connections

AssistantMD consumes MCP servers as a second-class tool source. It does not
expose an MCP server. Connection management is principal-owned even though the
current product resolves every interactive request as its single local user.

## Persisted connection contract

Sanitized connection definitions live in `system/mcp.db`. Each connection has:

- an immutable connection ID and immutable model-facing slug;
- an owner principal recorded in the database but not exposed in the API/UI;
- a display name, enabled state, Streamable HTTP or SSE transport, and URL;
- an optional exact-name tool allowlist;
- an explicit auth mode and, for custom-header auth, a non-secret header name;
- a monotonically increasing configuration version for runtime invalidation.

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

## Current management surface

The System tab can create, edit, enable, disable, and delete connections; select
Streamable HTTP or SSE; set an allowlist; and set or clear bearer/custom-header
credentials. Enabling a connection trusts the tools allowed by its policy:
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

Remote endpoints require HTTPS. Plain HTTP is accepted only for local/private
addresses when `ASSISTANTMD_MCP_ALLOW_INSECURE_HTTP=true`; `scripts/dev run`
sets that development allowance automatically. MCP clients ignore ambient HTTP
proxy configuration and do not follow redirects, preventing credentials from
being forwarded outside the explicitly configured endpoint.

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

OAuth tokens and dynamic client-registration state use the encrypted,
principal-and-connection-scoped secrets store. Chat and connection tests may use
and refresh an existing token, but they cannot initiate interactive
authorization. Disconnecting, deleting, or changing a connection away from
OAuth clears its stored OAuth state. Short-lived PKCE completion state is also
encrypted, allowing a callback or pasted redirect to complete after an
AssistantMD restart until the attempt expires.
