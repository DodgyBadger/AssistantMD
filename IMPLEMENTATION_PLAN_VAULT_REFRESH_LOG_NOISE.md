# Vault Refresh Activity Log Noise Plan

## Goal

Reduce activity-log rotation pressure from scheduled vault-state refreshes while
preserving diagnostics for refreshes that matter to users.

## Contract

- Every scheduled vault-state refresh still emits a validation event named
  `vault_state_scheduled_refresh_completed`.
- A scheduled refresh writes to `system/activity.log` only when it detects file
  changes or reports one or more vault refresh failures.
- The activity-visible payload includes refreshed/failed vault counts, created,
  changed, deleted file counts, total detected changes, and the latest sequence.

## Validation

- Extend `validation/scenarios/integration/core/vault_state_scheduled_refresh.py`
  to assert that a no-op scheduled refresh does not add a System Activity row.
- Assert that a scheduled refresh which observes an external file edit does add
  exactly one System Activity row for `vault_state_scheduled_refresh_completed`.

## Implementation

- Aggregate created, changed, and deleted file counts in
  `VaultStateService.refresh_all_vaults(...)`.
- Route scheduled refresh completion logging through validation-only sinks for
  no-op success results.
- Keep activity-visible logging for results with detected changes or failures.
