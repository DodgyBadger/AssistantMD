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

Live connection tests, managed transports, chat tool search, and MCP OAuth are
not active in this contract yet. The test endpoint returns a sanitized
`transport_unavailable` result until the runtime connection manager owns that
operation.
