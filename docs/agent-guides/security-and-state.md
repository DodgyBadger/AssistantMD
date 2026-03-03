# Security and Runtime State

- Never commit real API keys.
- Never commit populated `system/secrets.yaml`.
- Treat `/app/data` and `/app/system` as persistent runtime state during local testing.
