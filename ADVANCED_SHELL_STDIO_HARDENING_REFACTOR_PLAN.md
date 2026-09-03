# Advanced Shell and Stdio MCP Hardening Refactoring Plan

## Status

Implemented on `dev/mcp-stack-exploration` for the P1 lifecycle and protocol
defects, authority and canonical-metadata enforcement, managed-launch admission,
bounded test projection, readiness reporting, deployment identity validation,
and security-posture warning. No P0 issue was found. Targeted tests, the full
production Python quality gate, and all 104 deterministic `integration/core`
scenarios pass. The real two-image Docker smoke and manual System UI review
remain merge evidence.

The review originally considered a maximum enabled stdio connection count. That
restriction is deliberately absent: stored or enabled definitions do not justify
arbitrary user friction. Only concurrent AssistantMD-managed cold launches are
bounded, through the restart-required
`mcp_max_concurrent_advanced_shell_stdio_launches` setting. Direct shell processes
bypass this scheduling control and remain governed by aggregate container limits.

## Objective

Retain the current advanced-shell and advanced-shell stdio MCP architecture while
closing lifecycle leaks, making authority and persisted configuration
authoritative at every launch, aligning the structured-launch producer and
consumer contracts, and bounding contention for the shared advanced-shell
container.

The implementation must preserve:

- explicit restart-bound advanced mode;
- one deployment-owned SSH destination, identity, user, and pinned host key;
- literal structured argv for stdio providers with no shell parsing;
- principal-owned MCP identity, immutable slugs, allowlists, frozen catalogs,
  call budgets, and result shaping;
- no secret values or raw provider stderr in API responses or activity logs;
- active leases surviving configuration invalidation only for their owning run;
  and
- maintainer ownership of the complete validation profile.

## Architecture Assessment

The selected architecture is sound and consistent with AssistantMD. Arbitrary
operating-system capability is isolated in an optional, unprivileged companion
with a read-only base filesystem, explicit writable volumes, dropped
capabilities, and cgroup limits. AssistantMD reaches it through a mutually
authenticated, fixed-destination SSH channel. Interactive commands use the
forced shell boundary deliberately, while persisted stdio launches use a
versioned JSON/base64 envelope and literal argv. Stdio MCP then reuses the
existing connection service, durable mutation lifecycle, retained client
manager, catalog leases, tool allowlists, and chat execution accounting instead
of creating a parallel integration stack.

This is the right decomposition. The hardening findings are ownership and
contract-drift defects around the seams, not evidence that the companion or MCP
approach should be replaced.

## Prioritized Findings

### P1: execution lifecycle and cleanup

1. `core/chat/executor.py` acquires the MCP snapshot before entering the cleanup
   `try` in both ordinary preparation and deferred-review resume. An exception or
   cancellation while resolving the shell, constructing capabilities, or
   constructing recovery leaks the acquired leases. An invalidated retained
   stdio client can consequently keep its SSH/provider process until application
   shutdown.
2. `MCPConnectionManager.acquire_snapshot()` aggregates acquires with
   `asyncio.gather()`. Cancellation after one child has returned a lease but
   before all children settle loses ownership of the completed lease because no
   snapshot is constructed.
3. `FixedSshShellExecutor._execute()` stops its process group for timeout,
   output overflow, and cancellation, but an unexpected stream or subprocess
   exception reaches `finally` without stopping a still-running SSH process.
4. FastAPI lifespan shutdown follows a bare `yield`. Exceptional lifespan exit
   can skip `runtime.shutdown()` and retained MCP cleanup.

### P1: structured-launch and resource contracts

1. The producer permits 32 KiB of arguments plus sixteen 4 KiB environment
   values, then encodes without a total-size check. The forced-command consumer
   rejects decoded envelopes over 64 KiB. Accepted and persisted connections can
   therefore be deterministically unlaunchable.
2. A chat snapshot can request every enabled stdio connection concurrently. A
   configurable manager admission boundary is needed to limit managed cold-launch
   fan-out. This is an AssistantMD scheduling control, not a companion security
   boundary: direct `shell` commands can launch the same executables, while the
   companion's PID, memory, and CPU ceilings contain aggregate use.

### P2: authority and canonical configuration

1. The interactive shell permits only the local-user principal, but stdio MCP
   mutations and manager launch rely only on advanced mode. Current HTTP ingress
   resolves to local-user, making this latent, but a future nonlocal authority
   could use the shared single-user companion. One advanced-shell authority
   policy must govern both paths.
2. Manager authorization compares connection ID, version, and enabled state but
   launches fields supplied by the caller. A constructed connection with a real
   owned ID and matching version can substitute its URL or stdio launch metadata.
   Current callers use service-loaded records, but the manager boundary should
   load and launch authoritative persisted metadata itself.

### P2: bounded and explicit product behavior

1. Retained-manager connection tests return every effective tool name even
   though the superseded one-shot helper caps names at 100. A large remote
   catalog can inflate API and UI responses.
2. Stdio working-directory roots are lexical checks. Symlinks can resolve a path
   outside the named persistent roots. This is not a Unix-permission escape
   because the shell principal already has arbitrary execution, but the current
   “below allowed roots” wording overstates the guarantee.
3. Advanced mode permits offline stdio configuration even when readiness reports
   missing trust, authentication failure, or an unreachable companion. Preserve
   offline configuration if intentional, but expose readiness in the form and
   return a stable advanced-shell-unavailable test status.
4. The shipped authentication default is `disabled`, so the advanced-shell
   network peer can call the complete AssistantMD API. Documentation discloses
   this accurately. Decide whether advanced mode should require authenticated
   owner mode, require a separate acknowledgement, or emit a prominent startup
   and System warning.
5. Configurable container UID/GID values accept unsupported/root identities and
   provide no ownership repair contract for persistent volumes after an ID
   change.

### P3: maintainability and release consistency

1. The application and companion independently define the structured stdio
   protocol fields, limits, environment reservations, and path rules. The size
   mismatch demonstrates the need for cross-image conformance fixtures.
2. Client close currently occurs while the MCP manager's global state lock is
   held in one cold-start race path, allowing a bounded five-second cleanup to
   stall unrelated acquisitions.
3. `core/mcp/testing.py` duplicates an older HTTP-only connection-test path and
   no longer matches retained-manager stdio or network-policy behavior.
4. The two-image pairing smoke covers key exchange operationally, but maintained
   deterministic coverage does not exercise independent key-volume loss,
   mismatch, rotation, or startup-order inversion.
5. The advanced-shell release image receives SBOM/provenance output while the
   coupled main image does not have the same attestation settings.
6. `docker-compose.yml` contains two trailing-whitespace lines, reported by
   `git diff --check`.

## Validation-First Implementation Slices

### Slice 1: make lease and process ownership total

Add failing deterministic assertions before production changes:

- Extend the MCP chat scenario to fail each preparation step after snapshot
  acquisition and assert every lease is released exactly once for ordinary and
  deferred-resume preparation.
- Add a manager scenario with one completed acquire and one blocked acquire;
  cancel snapshot acquisition and assert the completed lease closes and the
  blocked connection task settles.
- Extend advanced-shell unit coverage with an unexpected stdin/stdout helper
  exception and assert TERM/KILL cleanup completes before the original exception
  escapes.
- Extend runtime bootstrap cleanup coverage with an exception raised through the
  lifespan body and assert runtime shutdown occurs once.

Then use explicit ownership transfer (prefer `AsyncExitStack` or a small owning
helper) in chat preparation, cancellation-safe settle-and-close logic in snapshot
acquisition, an authoritative process-stop path in the executor `finally`, and a
`try/finally` around the lifespan `yield`.

### Slice 2: centralize advanced-shell authority and persisted launch authority

- Introduce one predicate/service for principals allowed to use the single-user
  advanced shell.
- Apply it to shell capability resolution and stdio create, update, test,
  snapshot acquisition, and direct manager acquisition.
- Change manager acquisition to accept an identity and load the current active
  connection, or compare and replace the complete caller record with the
  authoritative service record before opening a transport.
- Add negative scenarios for a nonlocal principal and for caller-supplied launch
  metadata with a matching owned ID/version. Assert no SSH transport is created.

No persisted-data migration is required. Existing nonlocal stdio records, if
present through direct internal construction, must remain stored but unavailable
until an explicit tenancy design supersedes the single-user companion contract.

### Slice 3: make the stdio protocol bounded and conformant

- Specify the decoded JSON envelope budget, UTF-8 byte accounting, required
  fields, environment reservations, and version behavior in one protocol
  contract.
- Enforce the complete serialized budget before connection persistence and again
  in `encode_structured_launch()` as defense in depth.
- Keep the companion decoder independently fail-closed, but drive producer and
  decoder tests from shared conformance fixtures.
- Assert the largest accepted envelope decodes and launches, while the next byte,
  unknown fields, malformed base64, duplicate/invalid environment names, and an
  unknown version fail before persistence or execution as appropriate.
- Resolve working directories immediately before launch and enforce containment,
  or rename/document allowed roots as persistence namespaces rather than a
  security boundary. Prefer enforcement because it matches the current contract.

This slice changes MCP validation behavior but not the database schema. Existing
oversized rows should load as unavailable with a sanitized configuration error;
do not silently truncate argv or environment values.

### Slice 4: govern shared advanced-shell capacity

- Do not limit registered or enabled stdio definitions; persisted configuration
  should not create arbitrary user friction.
- Add the restart-bound
  `mcp_max_concurrent_advanced_shell_stdio_launches` setting and use it for a
  process-wide manager semaphore shared by cold starts and connection tests.
- Acquire capacity within the existing connection deadline and release it on
  every success, error, cancellation, invalidation, and shutdown path.
- Bound snapshot startup rather than scheduling every enabled provider at once.
- Return distinct sanitized capacity/queue-timeout availability, without raw SSH
  or provider diagnostics.
- Add deterministic concurrency assertions plus a targeted companion smoke with
  the configured PID ceiling. Document that direct shell processes do not consume
  manager permits and that only the container ceilings are aggregate containment.

### Slice 5: bound testing and remove duplicate paths

- Move effective-catalog filtering and the returned-name cap into one helper used
  by retained-manager tests.
- Preserve the complete effective count while returning at most 100 names and an
  explicit truncation message.
- Remove `core/mcp/testing.py` if no production caller remains, or reduce it to
  shared projection code with a name matching its role.
- Move client closes outside the manager global state lock and retain race
  assertions for invalidation during cold start.
- Add an advanced-shell-specific unavailable status and show readiness beside
  stdio configuration and test controls without forbidding intentional offline
  editing.

### Slice 6: deployment policy and polish

- Make an explicit product decision for `advanced` plus authentication
  `disabled`. The minimum acceptable result is a prominent structured startup
  warning and matching System status warning; the stronger result is an explicit
  acknowledgement or authenticated-owner default.
- Reject root, colliding, malformed, or unsupported UID/GID build arguments with
  clear errors and document a deliberate persistent-volume ownership repair
  procedure.
- Add deterministic key-material state tests and retain the two-image smoke for
  the real OpenSSH handshake and process-tree cleanup.
- Apply equivalent SBOM/provenance settings to both release images and verify the
  coupled tag set before advancing `latest`.
- Remove Compose trailing whitespace.

## Event Contracts

Reuse existing connection/readiness events where they already describe the
decision. Add events only for new operational decisions:

- `mcp_stdio_capacity_rejected`: `principal_id`, `connection_id`, `limit`, and
  `reason`; emitted when a launch cannot enter the bounded capacity window.
- `advanced_shell_security_posture_warning`: `execution_mode`, `auth_mode`, and
  `reason`; emitted once at startup when the selected deployment posture permits
  the companion to access the unauthenticated API.

Never include command text, argv, environment values, provider stderr, key
paths, or secret material in these events.

## Validation Targets

Primary deterministic targets:

- `validation/scenarios/integration/core/mcp_chat_tool_search.py` for snapshot
  ownership across chat preparation failures;
- `validation/scenarios/integration/core/mcp_connection_isolation.py` for
  manager cancellation, canonical metadata, capacity, and catalog projection;
- `validation/scenarios/integration/core/mcp_advanced_shell_stdio_connections.py`
  for authority gating, update/invalidation, protocol boundaries, readiness
  classification, and stdio cleanup;
- `validation/scenarios/integration/core/runtime_bootstrap_cleanup.py` for
  exceptional lifespan exit;
- `validation/test_advanced_shell_config.py` for executor exceptional cleanup and
  protocol boundary units; and
- `scripts/smoke_advanced_shell.sh` for the real two-image SSH handshake,
  cancellation, and PID cleanup.

Agents should run only the directly affected individual scenarios, unit files,
static analysis, and smoke checks. Before merge, request that maintainers run:

```bash
python validation/run_validation.py run integration/core
```

and report the result. The real Docker smoke and manual System UI workflow remain
separate explicit merge evidence.

## Affected Areas and Contract Sensitivity

- Execution lifecycle: `core/chat/executor.py`, `core/mcp/manager.py`,
  `core/tools/advanced_shell.py`, and `main.py`.
- Authority and runtime composition: `core/advanced_shell/`, `core/mcp/service.py`,
  and `core/runtime/bootstrap.py`.
- Persisted connection validation: `core/mcp/models.py`, `core/mcp/service.py`,
  and `system/mcp.db` rows. No schema migration is currently planned.
- Companion protocol and process ownership: `core/advanced_shell/stdio.py` and
  `docker/advanced-shell/forced_command.py`.
- Settings, API, and UI: `.env.example`, `api/models.py`, `api/services/mcp.py`,
  System status projection, and `static/js/configuration.js`.
- Deployment and release: both Dockerfiles, Compose files, pairing scripts,
  setup/security docs, and release workflow.

Configured data and system roots are persistent state. Tests must use isolated
temporary roots and must not mutate repository `data/`, `system/`, advanced-shell
named volumes, or real pairing keys. Stdio environment values remain sanitized
metadata in `mcp.db`; this plan does not move them into the encrypted secrets
store or imply that users may put credentials there.

## Next Phase

Proceed to Feature Development with Slice 1 only after its failing lifecycle
assertions are in place. Complete Slices 1 through 4 before merge readiness;
Slices 5 and 6 may be separate commits but should remain in the same hardening
effort so operational and contract drift does not become permanent.
