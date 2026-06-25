# Settings and Secrets Stores

AssistantMD separates infrastructure/runtime config from confidential values:

- Settings: `system/settings.yaml` (typed, template-seeded)
- Secrets: `system/secrets.yaml` (or `SECRETS_PATH` override)

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

Runtime-relevant general settings include:

- `chat_tool_calls_limit`: maximum tool calls allowed in one chat response; `0` disables the limit.
- `persist_model_reasoning_parts`: when false, provider reasoning/thinking
  parts are not persisted in durable chat history; when true, those parts are
  stored with provider-native messages, which can increase replay tokens and
  reduce portability across providers.
- `delegate_tool_calls_limit`: maximum tool calls allowed inside one `delegate` child-agent run; `0` disables the limit.
- `delegate_timeout_seconds`: maximum seconds allowed for one `delegate` child-agent run; `0` disables the timeout.
- `workflow_task_timeout_seconds`: maximum runtime seconds for a workflow execution task; `0` disables the workflow task timeout.
- `max_concurrent_workflows`: maximum workflows allowed to run at once across all vaults; `0` disables the global concurrency limit.
- `vault_state_enabled`: enable vault-state manifest refresh and change-feed maintenance.
- `vault_state_excluded_patterns`: gitignore-style vault-relative path patterns excluded from vault-state manifests and change feeds.
- `vault_scan_interval_seconds`: interval in seconds for the reserved `vault-state-refresh` scheduler job; `0` disables scheduled vault-state refresh.
- `task_rollback_enabled`: enable automatic rollback for failed, cancelled, or timed-out task file mutations.
- `task_mutation_retention_days`: days to retain task mutation audit rows before cleanup; defaults to 365 days.
- `task_snapshot_retention_days`: days to retain task snapshot metadata and files before cleanup; defaults to 30 days.
- `compaction_type`: chat history compaction policy (`auto`, `suggested`, or `none`). `auto` is the default and is recommended for long-running tasks; if compaction happens too often, tune `compaction_token_threshold` before switching to `suggested` or `none`.
- `compaction_keep_recent`: target count of recent raw chat messages preserved during compaction.
- `compaction_token_threshold`: estimated-token threshold for suggesting or automatically running compaction. Increase this first if automatic compaction happens too often.

## Secrets Store

Primary implementation: `core/settings/secrets_store.py`

Resolution:

1. `SECRETS_PATH` env var (authoritative if set)
2. otherwise `get_system_root() / "secrets.yaml"`

Key behavior:

- File is auto-created from `core/settings/secrets.template.yaml` if missing.
- Reads/writes are YAML-based and atomic.
- Empty values are normalized consistently.
- Helper APIs support list/get/set/remove/delete plus value-presence checks.

## Configuration Health and Availability

Primary implementation: `core/settings/__init__.py`

`validate_settings()` builds a `ConfigurationStatus` that drives:

- model availability warnings (missing provider secrets)
- tool availability warnings (missing required secrets)
- warnings for missing template entries
- warnings for unknown non-user-editable entries

This is why project-level tool additions should also be included in `core/settings/settings.template.yaml`: otherwise they can be flagged as unexpected/deprecated during config reconciliation.

## Configuration Editing APIs

Primary implementation: `core/settings/config_editor.py` and `api/services.py`

Behavior:

- user-editable models/providers can be created/updated/deleted through API
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
- Do not bypass reload paths after config writes.
- Prefer typed helpers in `core/settings/*` over ad-hoc YAML parsing in feature code.
