# Canonical Public URL Implementation Plan

Implementation status: completed on `dev/mcp-experimental` in four validated
slices.

## Goal

Give each AssistantMD installation an optional, canonical externally reachable
origin so security-sensitive absolute URLs remain correct behind reverse
proxies. The first consumer is MCP OAuth callback construction. The design must
remain useful for future webhooks and externally shared links without treating
request `Host` or forwarded headers as deployment truth.

## Current Findings

- Production and development already load deployment infrastructure from
  `.env`. `AppSettings` is the typed environment boundary, while
  `system/settings.yaml` contains user-editable runtime behavior and
  `system/secrets.db` contains principal-owned confidential values.
- Docker binds AssistantMD to loopback by default and expects remote installs
  to supply their own authenticated TLS reverse proxy. The backend therefore
  often sees an internal address that differs from the browser-visible origin.
- MCP OAuth currently has two competing callback sources: the backend fallback
  uses `request.url_for()`, while the frontend supplies `window.location` for
  interactive starts. This fixed the observed proxy mismatch but makes the
  browser request authoritative for a security-sensitive redirect.
- The MCP UI independently calculates and displays its callback URI. That
  duplicates callback policy and can drift from the value actually used.
- OpenAI OAuth is not a consumer of the new origin in this effort. Its
  loopback/device behavior is provider-specific and already has a separate
  contract.
- No persisted database migration is needed. This is instance-level deployment
  configuration and is neither principal-owned nor secret.

## Configuration Contract

Add the optional environment variable:

```text
ASSISTANTMD_PUBLIC_URL=https://assistant.example.com
```

Its value is an origin, not an arbitrary base path:

- require `https` for non-loopback hosts;
- allow `http` for `localhost`, `127.0.0.0/8`, and `::1` development origins;
- require a hostname and allow an explicit port;
- reject user information, query strings, fragments, and non-root paths;
- normalize only a trailing root slash, preserving the configured scheme,
  hostname, and port;
- reject a present but invalid value during startup with a sanitized,
  actionable configuration error;
- never resolve DNS or make a network request while validating the value.

The variable is optional for compatibility and local development. When absent,
features that need a browser callback may use an explicitly supplied browser
origin for that interactive request, but the System tab must identify that the
origin is inferred and explain that reverse-proxy deployments should configure
`ASSISTANTMD_PUBLIC_URL`.

## Runtime Ownership and URL Construction

1. Add a focused typed public-origin module under `core/runtime/` that owns
   parsing, normalization, source reporting, same-origin comparison, and safe
   joining of application-relative paths. Do not scatter `urljoin`, environment
   reads, or scheme/host validation across API handlers.
2. Add the parsed optional origin to `RuntimeConfig` and therefore
   `RuntimeContext`. Production bootstrap reads it once through the typed
   infrastructure-settings boundary; validation contexts can inject it
   explicitly without mutating global environment state.
3. Provide one helper that builds an absolute application URL from a leading
   slash. It must prevent network-path references (`//host`), traversal,
   query/fragment injection, and origin replacement.
4. Treat a configured origin as authoritative. Do not fall back to `Host`,
   `Forwarded`, or `X-Forwarded-*` values when it exists.
5. Do not globally override FastAPI request URL behavior or install permissive
   forwarded-header trust. Consumers must request canonical external URLs
   explicitly so internal URLs, outbound provider URLs, and provider-mandated
   loopback callbacks are not changed accidentally.

## MCP OAuth Integration

- Move callback-path construction to the backend and return the resolved
  callback URI as part of the sanitized MCP OAuth/UI contract.
- With `ASSISTANTMD_PUBLIC_URL` configured, ignore a client-supplied callback
  origin and build the callback from the canonical origin plus the owned
  connection ID.
- Without it, retain the current interactive browser-origin fallback. Validate
  the submitted URI with the existing OAuth checks and record that the fallback
  source was used; never persist the browser origin as installation config.
- Make the UI display the backend-resolved callback URI and its source instead
  of independently constructing it from `window.location`.
- Before starting authorization, compare the current browser origin with the
  configured public origin. A mismatch should produce clear guidance while
  still allowing headless/manual authorization; it must not silently substitute
  the browser origin.
- Keep authorization URL display and pasted-callback completion as fallbacks.
  PKCE, state comparison, expiry, encrypted pending state, and principal
  ownership remain unchanged.
- Log callback-source decisions (`configured` or `browser_fallback`) and
  origin-mismatch decisions without logging authorization URLs, query strings,
  codes, state values, client credentials, or tokens.

## System Status and User Experience

- Extend the status API with a sanitized public-URL block containing the
  normalized configured origin or `null`, its source, and whether configuration
  is recommended. Do not expose raw invalid input.
- Show the resolved deployment origin in the System tab.
- When unset, add a non-blocking System notice aimed at reverse-proxy and OAuth
  users. Local installations remain functional.
- When the browser origin differs from the configured origin, show both origins
  in the MCP OAuth panel with an explanation that callbacks use the configured
  value.
- The setting is read-only in the UI for this slice. The UI should point users
  to `.env` and state that changing it requires an application/container
  restart. AssistantMD must not rewrite installation `.env` files.

## Installation and Operations

- Add a commented `ASSISTANTMD_PUBLIC_URL` example to `.env.example`.
- Add the variable to `docker-compose.yml` through its existing
  `env_file` contract; do not duplicate its value in Compose `environment`.
- Update installation documentation with local, LAN, and reverse-proxy
  examples. Explain that it is the externally visible AssistantMD origin, not
  the internal container address, apex domain, or proxy upstream address.
- Update development documentation with an optional example for proxied dev
  environments. `scripts/dev setup` should not generate or guess the value.
- Extend `scripts/dev doctor` to report configured/unconfigured/invalid status
  without failing merely because the optional value is absent. An invalid
  present value should be reported as broken.
- Document that the reverse proxy remains responsible for TLS and
  authentication and must route the callback path to AssistantMD. This setting
  does not configure DNS, certificates, proxy trust, or access control.
- Existing installations require no migration. They continue using browser
  fallback until the operator opts into the canonical origin.

## Implementation Slices

### Slice 1: Typed origin boundary

- Implement normalization, validation, safe path joining, and typed source
  metadata.
- Wire the optional origin into infrastructure settings, `RuntimeConfig`, and
  `RuntimeContext`.
- Add deterministic unit/smoke coverage for valid HTTPS, loopback HTTP, IPv6,
  explicit ports, normalization, invalid schemes, credentials, paths, queries,
  fragments, and path-escape attempts.

### Slice 2: Status and installation surface

- Add the sanitized runtime status projection and System-tab display/warning.
- Update `.env.example`, installation, development, security, Compose guidance,
  and `scripts/dev doctor`.
- Prove missing configuration stays non-fatal and invalid present
  configuration fails before runtime services start.

### Slice 3: MCP OAuth authority migration

- Centralize MCP callback-path construction and replace the duplicated frontend
  calculation.
- Make configured origin authoritative and retain browser fallback only when it
  is absent.
- Add source/mismatch activity events and actionable API/UI messages.
- Preserve dynamic-registration, pre-registered-client, headless completion,
  restart-resumable pending state, and connection isolation behavior.

### Slice 4: Hardening and current-contract documentation

- Search again for absolute application URL construction and classify each
  consumer as canonical-origin, provider-defined, request-relative, or outbound.
- Update `docs/architecture/runtime.md` and
  `docs/architecture/mcp-connections.md` with the resulting current contract.
- Review log redaction, proxy-boundary behavior, startup failures, and UI state
  across reloads before the final quality gate.

## Validation Contract

Add or extend focused scenarios; maintainers retain ownership of the full
validation suite.

- A runtime/configuration scenario proves normalization and startup rejection
  rules without external network access.
- An API scenario with an injected canonical origin proves the MCP callback URI
  is built from that origin even when the request uses a conflicting host and a
  client submits a conflicting redirect URI.
- The same scenario proves an absent setting accepts a validated browser URI and
  reports `browser_fallback`.
- An MCP OAuth scenario proves both dynamic and pre-registered flows receive the
  resolved callback without changing PKCE/state/token-storage behavior.
- Status assertions prove the API/UI expose only normalized origin and source,
  and show a warning when configuration is absent.
- Installation artifact assertions cover `.env.example`, Compose/env-file
  guidance, restart behavior, and the distinction between public origin and
  reverse-proxy upstream.
- Targeted local checks include `scripts/dev doctor`, frontend syntax checking,
  and the production Python quality gate. Agents do not run the full validation
  suite.

## Contract-Sensitive Areas

- OAuth redirect allowlisting and authorization-code delivery.
- Trust boundaries among browser input, reverse-proxy headers, environment
  configuration, and runtime state.
- Startup failure versus diagnostics availability for invalid infrastructure
  configuration.
- API/status payload compatibility and System-tab warning behavior.
- Environment/Compose installation documentation and restart expectations.
- Validation isolation: tests must inject origins through `RuntimeConfig` rather
  than inheriting a developer's `.env`.

## Explicit Non-Goals

- Built-in authentication, TLS termination, DNS, certificate, or reverse-proxy
  configuration.
- Trusting arbitrary forwarded headers or changing Uvicorn proxy settings.
- Editing `.env` from the frontend.
- Persisting the public URL in `settings.yaml`, SQLite, or principal secrets.
- Supporting AssistantMD under a URL path prefix in this slice.
- Changing OpenAI's provider-defined loopback/device OAuth strategy.
- Automatically migrating future webhooks or externally shared links before
  their individual contracts are reviewed.

## Next Phase

The canonical public-origin milestone is implementation-complete. Request the
maintainer-owned full validation results and proceed through review preparation
and cleanup before merge. ADR 0036 records the resulting durable decision.
