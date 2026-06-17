# OpenAI OAuth Integration Plan

## Goal

Add an experimental OpenAI OAuth login path for the built-in `openai`
provider while keeping API-key auth the stable default. The implementation must
continue to use Pydantic AI for runtime model execution, keep secret material
out of normal settings, and degrade cleanly to API-key-only behavior when OAuth
is disabled or unavailable.

## Core Requirements

- Keep API-key auth fully supported for the built-in `openai` provider.
- Do not change auth behavior for Anthropic, Google, Grok, Mistral,
  OpenRouter, or generic OpenAI-compatible providers.
- Keep provider metadata in `system/settings.yaml` and secret material in
  `system/secrets.yaml`.
- Do not expose raw OAuth token fields in the generic Secrets UI.
- Add deterministic validation coverage for config shape, API artifacts,
  token-state decision boundaries, and runtime auth-mode resolution.
- Keep built-in providers non-editable by default.
- Add a built-in provider edit allowlist so selected built-ins can expose
  advanced metadata editing with clear warnings.
- Add a global OpenAI OAuth kill switch that disables OAuth immediately,
  ignores stored OAuth state, and forces API-key-only runtime behavior without
  deleting stored OAuth tokens.

## Resolved Design Decisions

### Auth Policy

- This is experimental Codex/ChatGPT OAuth for the built-in OpenAI provider,
  not a general OpenAI Platform OAuth replacement for API keys.
- OpenAI's documented stable path for programmatic API use remains Platform API
  keys. The design must account for policy/support changing without warning.
- The OAuth kill switch is authoritative. If `providers.openai.auth_mode` is
  `oauth` while global OAuth is disabled, the system reports the override and
  behaves as API-key-only. This is not a configuration error.
- Runtime OAuth-to-API-key fallback is disabled by default and must require an
  explicit provider setting. This avoids surprising Platform API charges. If
  OAuth fails and fallback is disabled, the user sees a clear warning and must
  either reconnect/fix OAuth or switch back to API-key mode.

### Runtime Boundary

- Do not assume Codex/ChatGPT OAuth bearer tokens are interchangeable with
  OpenAI Platform API keys against the normal OpenAI API base URL.
- Add an explicit Codex-compatible client/transport boundary owned by the
  OpenAI runtime factory. This boundary owns any Codex-specific base URL,
  headers, request adaptation, retry behavior, and compatibility constraints.
- The first implementation should be an internal client/transport adapter used
  by the OpenAI provider factory, not a separately exposed local HTTP proxy.
  Keep the boundary capable of evolving into an OpenAI-compatible local proxy if
  Pydantic AI compatibility requires it.
- Runtime model construction remains centralized in `core/llm/model_factory.py`.

### Configuration Contract

Add OpenAI-specific provider metadata without overloading `api_key`:

- `auth_mode`: user-selected intent, initially `api_key` or `oauth`.
- `oauth_api_key_fallback_enabled`: explicit runtime fallback opt-in, default
  `false`.
- Existing `api_key`: API-key secret pointer.
- Existing `base_url`: API-key/OpenAI-compatible endpoint metadata. Do not
  casually reuse it for OAuth unless the OAuth adapter deliberately needs it.

Add general settings:

- `openai_oauth_enabled`: global kill switch for all OAuth behavior.
- `editable_builtin_providers`: allowlist for protected built-in provider
  metadata editing. This is separate from OAuth enablement.

Status responses should distinguish:

- configured auth mode
- effective auth mode
- OAuth globally enabled/disabled
- fallback enabled
- fallback available
- OAuth connection status
- sanitized OAuth metadata such as account id, token expiry, last refresh time,
  sanitized refresh failure category/message, and pending auth expiry

Status responses must not include access tokens, refresh tokens, authorization
codes, PKCE verifier values, or raw token endpoint responses.

### OAuth State

- AssistantMD owns one active OpenAI OAuth token state initially. Multiple named
  OAuth profiles are out of scope for the first implementation.
- Store OAuth token state in `system/secrets.yaml` through the secrets store.
- Hide internal OAuth token and pending-auth entries from the generic Secrets
  list by default. Expose only sanitized state through provider/OAuth status.
- Disconnect clears OAuth token and pending auth state only. It does not change
  `auth_mode`; if OAuth remains selected, status prompts the user to reconnect
  or switch auth mode.

### OAuth Start And Completion

- Use PKCE.
- Split OAuth into start and complete API steps.
- `start` persists short-lived pending auth state server-side:
  `state`, `code_verifier`, `redirect_uri`, `created_at`, `expires_at`, and
  optional return metadata.
- Pending auth state is secret material and should be stored through the secrets
  store with lazy TTL cleanup.
- Only one pending OpenAI OAuth attempt is allowed at a time. Starting a new
  connect flow replaces any previous pending attempt.
- Completion supports both:
  - automatic callback with `state` and `code`
  - manual paste of the final redirect URL, with raw authorization code accepted
    only when it can be resolved unambiguously
- Pending auth state is single-use.
- Device-code auth is deferred. PKCE with automatic callback plus manual paste
  completion covers the initial remote/headless deployment requirement.

### Logging And Validation

- Token exchange/refresh goes through a service-level adapter boundary so
  validation can inject deterministic fakes without product settings for fake
  OAuth endpoints.
- Logs use sanitized, low-cardinality fields only.
- UI status may show account id. Logs should default to `has_account_id`, not
  the actual account identifier.
- Never log tokens, auth codes, PKCE verifier/state values, pasted redirect
  URLs, raw token endpoint responses, or full account identifiers.

## Current Code Reality

### Runtime Model Construction

- `core/llm/model_factory.py`
  - builds model instances
  - current `openai` branch resolves `api_key` and `base_url`, then constructs
    `OpenAIProvider(...)`
- `core/llm/model_utils.py`
  - resolves provider config
  - validates provider credential presence before runtime use
- `core/settings/__init__.py`
  - computes model availability warnings shown in UI/API

### Settings And Secrets

- `core/settings/store.py`
  - `ProviderConfig` currently models `api_key`, `base_url`, `provider`, and
    `user_editable`
- `core/settings/config_editor.py`
  - provider writes are currently limited to API-key/base-url metadata and
    user-editable providers
- `core/settings/settings.template.yaml`
  - built-in `openai` points to `OPENAI_API_KEY`
- `core/settings/secrets_store.py`
  - supports hot-reloadable secret persistence and is the right storage path
    for OAuth token and pending PKCE material

### API And UI

- `api/models.py`
  - `ProviderInfo` and `ProviderConfigRequest` are API-key/base-url shaped
- `api/services.py`
  - provider CRUD and provider status are built here
  - secrets list is derived from provider/tool references
- `api/endpoints.py`
  - exposes provider and secret endpoints
- `static/js/configuration.js`
  - provider list/form only understand `api_key` and `base_url`
  - built-in providers are currently presented as read-only

### Validation Seam

- `validation/scenarios/integration/core/api_endpoints.py`
  - already covers provider CRUD and secrets lifecycle
  - should be extended for provider response shape, auth-mode updates, and
    deterministic OAuth endpoint lifecycle assertions

## Implementation Slices

The implementation should proceed in small vertical slices. Each slice should
end with an API artifact, deterministic smoke test, or validation assertion so
the next step does not need to make hidden assumptions.

### Slice 1: Config And Provider Status Contract

Define the typed config and API response contract before runtime behavior
changes.

Changes:

- Extend `ProviderConfig` with OpenAI auth metadata:
  `auth_mode` and `oauth_api_key_fallback_enabled`.
- Add general settings for `openai_oauth_enabled` and
  `editable_builtin_providers`.
- Update config editing so built-in provider edits are allowed only when the
  provider is in the allowlist.
- Update the OpenAI settings template defaults with API-key mode and OAuth
  disabled.
- Extend provider API models with configured/effective auth mode, fallback
  flags, OAuth enabled state, OAuth status, and sanitized metadata.
- Ensure custom provider CRUD remains unchanged.

Testable artifacts:

- `GET /api/system/providers` returns enriched OpenAI provider metadata.
- `PUT /api/system/providers/openai` can update allowed non-secret OpenAI auth
  metadata only when built-in editing is allowed.
- Turning `openai_oauth_enabled` off makes OpenAI provider status and runtime
  availability behave as API-key-only.
- Existing custom provider CRUD behavior remains unchanged.

Validation target:

- Extend `validation/scenarios/integration/core/api_endpoints.py` for the new
  OpenAI provider response shape and built-in editability boundaries.

### Slice 2: OAuth State Service With Fake Adapter

Add a dedicated OpenAI OAuth state manager that owns token persistence, pending
PKCE state, refresh semantics, and sanitized status. Use deterministic adapter
fakes here; do not depend on real OpenAI OAuth behavior in this slice.

Changes:

- Add an OpenAI OAuth service under `core/llm/`.
- Persist one active OAuth token state through `core/settings/secrets_store.py`.
- Persist one pending PKCE state with `expires_at`, single-use completion, and
  lazy cleanup.
- Replace stale/existing pending state when a new start request is created.
- Normalize expiry handling.
- Hide internal OAuth secrets from the generic Secrets list.
- Expose sanitized connection/account/expiry/refresh/pending status.
- Route token exchange and refresh through an injectable service-level adapter.
- Add sanitized decision logging:
  - `openai_auth_mode_resolved`
  - `openai_oauth_refresh_attempted`
  - `openai_oauth_refresh_result`

Testable artifacts:

- Token state parsing and expiry logic.
- Pending auth expiry, stale cleanup, and single-use completion.
- Refresh-required versus no-refresh-required branches.
- Internal OAuth secret entries do not appear in the generic Secrets list.

Validation target:

- API-visible OAuth status assertions using deterministic token adapter fakes.

### Slice 3: Connect Lifecycle API With Fake Exchange

Expose the OAuth connect lifecycle end to end through API surfaces while token
exchange remains fake/deterministic.

Changes:

- Add OpenAI-specific endpoints in `api/endpoints.py` with thin orchestration in
  `api/services.py`:
  - start OAuth
  - complete automatic callback
  - complete manual pasted redirect URL or authorization code
  - fetch OAuth/provider status
  - disconnect OAuth
- Keep provider CRUD separate from OAuth token-bearing flows.
- Use service-level token exchange/refresh fakes for lifecycle validation.

Testable artifacts:

- Starting OAuth returns redirect/bootstrap data and persists pending state.
- Callback completion persists token state.
- Manual paste completion works when the backend callback is unreachable from
  the user's browser.
- Disconnect clears OAuth token and pending auth state without changing
  `auth_mode`.
- Provider status reflects connection changes after reload.

Validation target:

- Deterministic OAuth endpoint lifecycle assertions using service-level token
  exchange/refresh fakes.

### Slice 4: Runtime Auth-Mode Resolver

Add runtime auth decision logic without committing yet to the real
Codex-compatible adapter internals.

Changes:

- Add an OpenAI auth-mode resolver that classifies:
  - API-key mode
  - OAuth connected mode
  - OAuth selected but disconnected/failed
  - OAuth disabled by global kill switch
  - OAuth failure with explicit API-key fallback enabled
- Update `core/llm/model_utils.py` and `core/settings/__init__.py` so
  availability checks use the resolver.
- Add sanitized decision logging for auth-mode resolution and fallback
  decisions.

Testable artifacts:

- API-key mode remains available when `OPENAI_API_KEY` is configured.
- OAuth-connected mode can mark OpenAI available without `OPENAI_API_KEY`.
- OAuth failure without explicit fallback produces a clear warning/error.
- OAuth failure with explicit fallback and configured API key selects API key.
- Global OAuth disable forces API-key-only availability even when valid OAuth
  tokens are stored.

Validation target:

- Provider/config scenario assertions plus targeted local smoke tests for
  resolver decision boundaries.

### Slice 5: Codex-Compatible Runtime Adapter

Integrate OAuth into the Pydantic AI runtime path without spreading auth
branching through request code. This is the highest-unknown slice and should
stay isolated from config/API/UI work.

Changes:

- Add an OpenAI-specific runtime factory in `core/` that:
  - builds normal API-key `OpenAIProvider` instances
  - builds OAuth-backed Pydantic AI-compatible clients through the
    Codex-compatible internal adapter boundary
  - uses explicit API-key fallback only when
    `oauth_api_key_fallback_enabled` is true
- Update `core/llm/model_factory.py` OpenAI branch to call the factory.

Testable artifacts:

- API-key mode still constructs OpenAI models.
- OAuth-connected mode constructs a Pydantic AI-compatible OpenAI provider
  through the internal Codex-compatible adapter boundary.
- OAuth failure without explicit fallback produces a clear warning/error.
- OAuth failure with explicit fallback and configured API key uses API key.
- Global OAuth disable forces API-key-only runtime construction even when valid
  OAuth tokens are stored.

Validation target:

- Targeted local smoke tests for factory and adapter behavior.

### Slice 6: Configuration UI

Expose OAuth as a coherent OpenAI connection option in the Configuration tab.

Changes:

- Add an OpenAI provider detail surface for built-in metadata and connection
  state.
- Render:
  - configured/effective auth mode
  - global OAuth enabled/disabled status
  - connection status
  - account id, expiry, last refresh, and sanitized refresh failure metadata
  - connect/reconnect/disconnect actions
  - manual paste completion
  - API-key pointer/readiness
  - explicit OAuth failure fallback opt-in
- Preserve existing custom provider editing behavior.
- Keep OAuth controls visible but disabled when global OAuth is disabled.
- Do not require manual OAuth token editing in the Secrets UI.

Testable artifacts:

- OpenAI provider card reflects auth mode, connection state, fallback readiness,
  and global kill-switch override.
- Custom provider editing still behaves as before.
- Generic Secrets UI/list does not show internal OpenAI OAuth token or
  pending-auth entries by default.

Validation target:

- API scenario coverage for backing endpoints.
- Maintainer browser smoke verification.

### Slice 7: Hardening, Docs, And Merge Prep

Reduce drift risk and make the feature maintainable.

Changes:

- Update `docs/architecture/settings-secrets.md` with the OpenAI auth split,
  kill switch, built-in edit allowlist, and hidden internal OAuth secrets.
- Add concise usage notes for the Configuration UI if needed.
- Review logs for useful auth diagnostics without token/account leakage.
- Confirm no real OAuth tokens or populated secret files are committed.

Testable artifacts:

- Docs match shipped API/UI behavior.
- Validation scenarios cover the stable contract.
- Manual review confirms no secret material is exposed in logs, responses, or
  committed files.

## Suggested Implementation Order

1. Config and provider status contract.
2. OAuth state service with deterministic token adapter fakes.
3. Connect lifecycle API using fake exchange/refresh.
4. Runtime auth-mode resolver and availability checks.
5. Codex-compatible runtime adapter.
6. Configuration UI.
7. Docs, logging review, and merge prep.

## Current Progress

- Slice 1 implemented:
  - typed OpenAI provider auth metadata
  - `openai_oauth_enabled` and `editable_builtin_providers` settings defaults
  - allowlisted built-in provider metadata editing
  - enriched OpenAI provider status response
  - API scenario assertions for default OpenAI status and allowlisted auth
    metadata updates
- Slice 2 implemented:
  - internal OpenAI OAuth token and pending-state persistence helpers
  - pending PKCE TTL cleanup, replacement, and single-use consumption
  - service-level token exchange/refresh adapter protocol and deterministic
    result type
  - sanitized OAuth status object wired into OpenAI provider status
  - internal OAuth secret filtering from the generic Secrets list
  - API scenario assertion for hidden internal OAuth token state
- Slice 3 implemented:
  - PKCE OAuth start helper with persisted pending state and bootstrap URL
  - callback and manual completion helpers using the injectable token adapter
  - OpenAI OAuth start/callback/manual-complete/status/disconnect endpoints
  - deterministic static adapter coverage in the API scenario
  - disconnect clears token and pending state without changing provider auth mode
- Slice 4 implemented:
  - centralized OpenAI auth resolver for configured/effective auth modes
  - runtime `validate_api_keys` now accepts connected OAuth and explicit
    fallback paths
  - configuration health/model availability now reflects OAuth connected,
    disconnected, fallback, and kill-switch states
  - provider status uses the resolver for effective auth mode and fallback
    availability
  - API scenario asserts model availability changes with OAuth connect/disconnect
- Slice 5 implemented:
  - OpenAI model construction now routes through a dedicated runtime factory
  - API-key and explicit fallback modes build normal Pydantic AI OpenAI providers
  - OAuth effective mode routes through an injectable runtime adapter boundary
  - OAuth mode fails clearly when the real Codex-compatible adapter is not
    configured

## Local Smoke Tests During Development

- Provider config validation by auth mode.
- Built-in provider edit allowlist behavior.
- Global OAuth kill-switch override.
- OAuth token state persistence and hidden-secret filtering.
- Pending PKCE state expiry, stale cleanup, replacement, and single-use
  completion.
- Token refresh required versus no-refresh-required decisions.
- OpenAI runtime factory output for API-key, OAuth, disabled, failed, and
  explicit-fallback branches.

## Validation Requests For Maintainers

- Full run of the updated integration scenario covering:
  - provider API shape
  - OpenAI auth mode updates
  - built-in edit allowlist behavior
  - OAuth connect/disconnect lifecycle with deterministic fakes
  - model availability changes tied to auth state and kill-switch state
- Manual browser verification of the Configuration tab OpenAI provider flow.

## Planning Exit Criteria

- OpenAI auth remains scoped as an experimental built-in-provider feature.
- API-key behavior remains stable and default.
- OAuth can be disabled globally with one setting.
- Runtime fallback to API key is explicit opt-in.
- Remote/headless completion is first-class through manual paste.
- Feature development can proceed in small slices with deterministic API
  artifacts and explicit decision-boundary logging.
