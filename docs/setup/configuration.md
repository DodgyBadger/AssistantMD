# Configuration Guide

AssistantMD separates **non-secret settings** from **secrets** so you can safely edit everything from the Configuration tab or directly on disk.

## Configuration Sources
- `system/settings.yaml` – models, providers, tools, and general settings (non-secrets). It is created automatically if missing.
- `system/secrets.yaml` – secrets such as API keys or private base URLs. When missing, it is seeded from `core/settings/secrets.template.yaml` with all known keys (models, tools, telemetry) and should remain untracked in version control.

## Using the Configuration Tab
Open the web UI → **Configuration**.

### Application Settings
- Lists every key/value stored under the `settings` section of `system/settings.yaml`.
- Click **Edit** to change the value inline. Booleans accept `true/false`.
- Saving hot-reloads the setting unless it is marked “Restart recommended.”

### Models
- Adds or edits aliases that map to provider-specific model identifiers.
- Availability reflects validation (missing API keys, unknown providers, etc.).
- Removing a model alias removes it from `system/settings.yaml`.

### Providers
- Manages API key/base URL metadata used by model aliases.
- Entering a value stores it in the secrets store; clearing blanks the value.
- Built-in providers show as read-only.

### Secrets
- Lists all known secret names (providers, tools, telemetry).
- **Update** prompts for a new value (masked after save). **Clear** removes the stored value.
- Changes apply immediately—no container restart required.
- Secrets are persisted in plain text at `system/secrets.yaml`; protect the file with normal filesystem permissions/backups.

### System Log
- The activity log viewer remains unchanged; use **Refresh** to pull the latest entries.

## Editing Files Directly
- Non-secret configuration: edit `system/settings.yaml` and refresh configuration from the UI or restart the container.
- Secrets: edit `system/secrets.yaml` manually if needed, then choose **Configuration → Secrets → Refresh** to reload values (no restart required).

## Infrastructure Variables
A small set of infrastructure values (the vault mount path, host port binding, and optional `TZ`) remain in `docker-compose.yml`. Update the compose file and restart the stack when those values change.
