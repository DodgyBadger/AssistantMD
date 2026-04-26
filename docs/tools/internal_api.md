# `internal_api`

## Purpose

Fetch structured metadata from a small allowlist of internal read-only API endpoints.

This tool is currently disabled by default. If enabled, use it only for the supported read-only metadata endpoints.

## Parameters

- `endpoint`: required. One of `metadata` or `context_templates`.
- `vault_name`: optional. Used by `context_templates` when the active vault cannot be inferred.
- `workflow_name`: reserved for future allowlisted endpoints.

## Notes

- This is not a general HTTP client.
- Unsupported endpoints are rejected.
