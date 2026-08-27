# 0041 - Bind Google OAuth State To Credential Generations

## Status

Accepted.

## Context

A Google OAuth client ID identifies the credential relationship under which a
grant was created. Treating it like ordinary display metadata can leave tokens
or pending authorization attempts usable after the client identity changes.
Deleting stale records best-effort is not sufficient because cleanup can fail,
and changing a client ID from `A` to `B` and back to `A` can otherwise revive
state from the first generation.

## Decision

Give every Google connection a positive monotonic OAuth generation. Increment
it exactly once when the normalized client ID changes; display name, default
selection, and capability-preference changes preserve it.

Store a random credential identity with each client secret and replace that
identity whenever the secret is replaced. Bind token grants and pending PKCE
state to both the connection's OAuth generation and the current credential
identity. Status resolution, OAuth start and completion, refresh, and
capability availability reject mismatched bindings before using or exchanging
the state.

A client-ID change invalidates the previous client secret, pending attempt,
token grant, account identity, and capability readiness. Replacing only the
client secret invalidates pending attempts and grants while preserving the
client ID generation. Cleanup removes stale encrypted records when possible,
but binding verification is the authoritative invalidation mechanism.

An authenticated unbound legacy client secret may be assigned to generation 1
on first use. Unbound legacy tokens and pending attempts require
reauthorization; silently binding them could preserve grants created under a
different client identity.

Keep generation and credential identities internal. APIs and activity logs
expose sanitized readiness transitions, not binding values or stale account
data.

## Consequences

- Changing security-sensitive credential identity differs intentionally from
  editing connection presentation or preferences.
- Returning from client ID `B` to `A` cannot revive grants from an earlier `A`
  generation.
- OAuth persistence and readiness checks must carry and verify both bindings.
- Conservative legacy handling may require users to reconnect rather than
  preserving an unverifiable grant.
- Physical stale-record cleanup remains useful for hygiene but is not part of
  the authorization proof.

## Evidence

- Implementation plan: `BRANCH_HARDENING_IMPLEMENTATION_PLAN.md`, Stage 3
- Current implementation boundaries: `core/integrations/google/connection.py`
  and `core/integrations/google/oauth.py`
- Related decisions: ADR 0028, ADR 0034, ADR 0037, and ADR 0038
