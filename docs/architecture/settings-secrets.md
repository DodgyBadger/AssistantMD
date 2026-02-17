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
- `tools`: tool registry used by chat/workflows (`@tools` resolution)

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
