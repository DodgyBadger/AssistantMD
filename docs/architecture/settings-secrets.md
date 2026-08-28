# Settings and Secrets Stores

AssistantMD separates infrastructure/runtime config from confidential values:

- Settings: `system/settings.yaml` (typed, template-seeded)
- Secrets: principal-owned encrypted records in `system/secrets.db`

This page documents how each store works and how reload/validation interacts with them.

## Settings Store

Primary implementation: `core/settings/store.py`

Key behavior:

- If `system/settings.yaml` is missing, it is seeded from `core/settings/settings.template.yaml`.
- Settings are validated through Pydantic models (`SettingsFile`, `ToolConfig`, `ModelConfig`, `ProviderConfig`).
- Reads are cached (`load_settings()` with `lru_cache`), then refreshed via `refresh_settings_cache()`.
- Writes are atomic (`*.tmp` + `os.replace`).

Sections:

- `settings`: general app settings (timeouts, defaults, routing controls, ingestion settings)
- `models`: alias -> provider/model-string mapping
- `providers`: provider wiring (secret pointer names, optional base-url pointers)
- `tools`: tool registry used by chat, delegate child agents, and authored direct-tool calls

Provider wiring can include provider-specific auth metadata. The built-in
`openai` provider supports `auth_mode` (`api_key` or `oauth`) and
`oauth_api_key_fallback_enabled`. API-key mode is the stable default. OAuth mode
is experimental and is controlled by the global `openai_oauth_enabled` setting;
when that setting is false, OpenAI resolves as API-key-only even if OAuth tokens
are stored. OAuth fallback to API-key auth is opt-in so runtime model requests
do not silently switch billing paths.

Runtime-relevant general settings include:

- `default_chat_mode`: initial mode for new chat sessions (`normal` or
  `inline_edit`). A session persists its own selected mode after creation.
- `disabled_tools`: app-wide denylist of tool registry names. Registered tools
  are available to chat, delegate child agents, workflows, context scripts, and
  code execution unless listed here. Chat does not maintain a separate
  per-session tool selection.
- `web_search_strategy`, `web_extract_strategy`, and `web_crawl_strategy`:
  provider strategy identifiers for the stable web capabilities. Strategy
  selection is explicit; failures do not trigger another provider.
- `ingestion_url_fetch_strategy`: URL transport used by durable ingestion,
  independently of agent web extraction.
- `ingestion_url_connect_timeout_seconds`,
  `ingestion_url_read_timeout_seconds`, and
  `ingestion_url_max_response_mb`: bounded URL-ingestion transport limits.
- `ingestion_ocr_timeout_seconds`: maximum duration of one OCR provider request.
- `content_import_max_batch_size`: maximum sources or job ids accepted by one
  `content_import` tool call.
- `browser_max_concurrent_sessions`, `browser_max_calls_per_turn`, and
  `browser_min_memory_headroom_mb`: Chromium concurrency, task budget, and
  cgroup launch-admission controls.
- `chat_tool_calls_limit`: maximum tool calls allowed in one chat response; `0` disables the limit.
- `chat_model_requests_limit`: maximum model requests allowed in one chat
  response; `0` disables the circuit breaker.
- `model_stream_retries`: retries after a retryable model-stream disconnect in
  primary chat and delegate runs; `0` disables automatic retries. Primary chat
  uses effect-aware checkpoints, while a delegate retries only before any child
  tool effect. Both paths must prove that retry will not duplicate tool effects.
- `model_stream_retry_base_delay_seconds` and
  `model_stream_retry_max_delay_seconds`: initial and maximum delays for bounded
  exponential stream-retry backoff.
- `file_list_max_results`: maximum structured results returned by
  `file_read(list)`; `0` disables the cap.
- `file_search_timeout_seconds`: timeout for `file_read(search)`.
- `persist_model_reasoning_parts`: when false, provider reasoning/thinking
  parts are not persisted in durable chat history; when true, those parts are
  stored with provider-native messages, which can increase replay tokens and
  reduce portability across providers.
- `delegate_tool_calls_limit`: maximum tool calls allowed inside one `delegate` child-agent run; `0` disables the limit.
- `delegate_model_requests_limit`: maximum model requests allowed inside one
  delegate child-agent run; `0` disables the limit. Keep at least one of the
  delegate model-request, tool-call, or timeout limits enabled to retain runaway
  protection.
- `delegate_repeated_failure_limit`: maximum consecutive structured failures
  allowed for one delegate child tool with identical arguments before later
  unchanged attempts are blocked; `0` disables the guard.
- `delegate_timeout_seconds`: maximum seconds allowed for one `delegate` child-agent run; `0` disables the timeout.
- `workflow_task_timeout_seconds`: maximum runtime seconds for a workflow execution task; `0` disables the workflow task timeout.
- `max_concurrent_workflows`: maximum workflows allowed to run at once across all vaults; `0` disables the global concurrency limit.
- `vault_state_enabled`: enable vault-state manifest refresh and change-feed maintenance.
- `vault_state_excluded_patterns`: gitignore-style vault-relative path patterns excluded from vault-state manifests and change feeds.
- `vault_scan_interval_seconds`: interval in seconds for the reserved `vault-state-refresh` scheduler job; `0` disables scheduled vault-state refresh.
- `task_rollback_enabled`: enable automatic rollback for failed, cancelled, or timed-out task file mutations.
- `task_mutation_retention_days`: days to retain attributed vault activity and mutation rows before cleanup; defaults to 365 days.
- `task_snapshot_retention_days`: days to retain task snapshot metadata and files before cleanup; defaults to 30 days.
- `compaction_type`: chat history compaction policy (`auto`, `suggested`, or `none`). `auto` is the default and is recommended for long-running tasks; if compaction happens too often, tune `compaction_token_threshold` before switching to `suggested` or `none`.
- `compaction_keep_recent`: target count of recent raw chat messages preserved during compaction.
- `compaction_token_threshold`: estimated-token threshold for suggesting or automatically running compaction. Increase this first if automatic compaction happens too often.
- `openai_oauth_enabled`: authoritative kill switch for experimental OpenAI OAuth behavior.
- `editable_builtin_providers`: built-in provider names whose non-secret metadata may be edited through the configuration API/UI. Built-in providers remain protected from deletion.

## Secrets Store

Primary implementation: `core/settings/secrets_store.py`

Key behavior:

- AES-256-GCM encrypts every value with identity-bound authenticated metadata.
- `ASSISTANTMD_SECRETS_KEY` supplies the installation's URL-safe Base64-encoded
  32-byte key. Stored records retain an internal key version for future safe
  rotation support.
- Generic provider and tool credentials belong to the active execution
  principal. System infrastructure credentials such as `LOGFIRE_TOKEN` belong
  to the system principal.
- Missing, malformed, or non-matching key material puts secrets into a locked
  state. The application remains available for diagnostics, while provider and
  model use remains unavailable until the installation key is restored.
- Helper APIs support list/get/set/remove/delete plus value-presence checks
  without exposing records owned by another principal.

OpenAI OAuth token state, pending PKCE state, and pending device-code state are
persisted as internal, principal-owned secret entries so they survive restarts.
Those internal entries are not returned by the generic Secrets UI/API list and
should only be accessed through `core/llm/openai_oauth.py`. Pending auth state
has a short TTL and is lazily cleared when status or completion paths observe
that it has expired.

Built-in Google connections keep named, non-secret client metadata and
capability preferences in principal-owned `connections.db` records. Each
connection has an immutable ID and slug, and one connection is the principal's
default. OAuth client secrets, pending PKCE requests, tokens, granted scopes,
and connected account identities use connection-scoped internal entries in the
`oauth.google` encrypted namespace. Generic Secrets APIs do not expose those
entries. Google capabilities become available when at least one stored grant
contains their required scopes.

Each Google connection carries an internal OAuth generation. Client secrets,
pending authorization attempts, and token grants are encrypted with payload
metadata binding them to that generation and to the current client-secret
identity. Changing the OAuth client ID advances the generation; replacing the
client secret changes the credential identity. Status, callback completion,
refresh, and capability checks reject stale bindings before using credentials
or contacting Google. Display, default, and Gmail preference changes preserve
the generation and existing authorization.

OAuth completion and refresh retain the credential binding verified before the
external request. Token persistence compares that binding with the encrypted
client-secret record and writes the grant in one secrets-store transaction, so
an in-flight response cannot recreate token state after a concurrent credential
replacement.

Disconnect preserves the configured client-secret value but atomically rotates
its internal credential identity while deleting pending and token state. An
in-flight completion or refresh therefore either settles before disconnect and
is deleted, or observes the rotated identity and cannot persist afterward.
The rotation compares the exact credential it observed and retries when another
credential mutation wins first, so disconnect cannot restore an older client
secret. Refresh persistence also compares the exact source grant, preventing an
older refresh response from overwriting a newer completed authorization.

Google connection deletion removes metadata before clearing the captured
encrypted namespace. A concurrent client-secret writer rechecks the immutable
connection identity after its write and conditionally removes its exact payload
when deletion won, preventing orphaned credential material across the separate
connections and secrets databases.
The metadata transaction also records a sanitized permanent deletion ledger.
Startup and idempotent item-route retries reconcile every recorded immutable ID
by clearing its exact encrypted connection namespace. Retaining the ledger
closes the crash window in which a writer that captured pre-deletion metadata
commits immediately before process death. When deleting the default connection,
shared legacy OAuth identities are cleared before its replacement becomes the
default, so lazy migration cannot move legacy credentials across identities.

Internal OAuth state relocation and multi-record cleanup execute as one
`secrets.db` transaction. Because encrypted record identity participates in
authenticated encryption, relocation decrypts the source identity, re-encrypts
for the destination identity, verifies the destination, and removes the source
before commit. Google disconnect and deletion atomically clear all applicable
connection and default-connection OAuth identities so removed state cannot be
loaded again through another namespace.

Internal connection mutation helpers can also copy staged values while retaining
their source as recovery evidence, delete an exact principal-owned namespace,
and condition a write on an authenticated encrypted guard. Copy, deletion, guard
comparison, target authentication, and commit remain within one secrets-store
transaction. These primitives support durable cross-database coordination
without exposing OAuth storage hashes or secret values to connection metadata.

## Configuration Health and Availability

Primary implementation: `core/settings/__init__.py`

`validate_settings()` builds a `ConfigurationStatus` that drives:

- model availability warnings (missing provider secrets)
- tool availability warnings (missing required secrets)
- warnings for missing template entries
- warnings for unknown non-user-editable entries

Web capability availability includes requirements declared by the selected
strategy. For example, selecting `tavily` makes that capability unavailable
with a configuration warning until `TAVILY_API_KEY` is populated. The runtime
does not substitute a secret-free strategy. Configuration health also warns
when browser is enabled under a detectable memory limit below the supported
2 GB browser-capable baseline.

This is why project-level tool additions should also be included in `core/settings/settings.template.yaml`: otherwise they can be flagged as unexpected/deprecated during config reconciliation.

## Configuration Editing APIs

Primary implementation: `core/settings/config_editor.py` and
`api/services/configuration.py`

Behavior:

- user-editable models/providers can be created/updated/deleted through API
- allowlisted built-in providers can edit supported non-secret metadata, but are not user-deletable
- general settings are type-coerced and validated
- secrets are managed separately from provider/model metadata
- every successful update runs reload (`reload_configuration`) so caches/status stay current

## Reload Semantics

`core/runtime/reload_service.py` handles hot reload:

- refresh settings and model caches
- refresh app-settings and config-status caches
- refresh logfire configuration
- stamp runtime with `last_config_reload` when runtime exists

`restart_required` is surfaced in API responses when a changed setting declares restart requirements.

## Practical Rules for Contributors

- Built-in/default config changes should update the settings template, not just active `system/settings.yaml`.
- Keep secret names as pointers in provider/tool config; store secret values only in secrets store.
- Keep provider-specific secret state behind subsystem helpers rather than exposing it through generic Secrets APIs.
- Do not bypass reload paths after config writes.
- Prefer typed helpers in `core/settings/*` over ad-hoc YAML parsing in feature code.
