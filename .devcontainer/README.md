# Devcontainer (envbuilder/Coder)

This devcontainer uses envbuilder for Coder workspaces. Key choices:

- Base image: `mcr.microsoft.com/devcontainers/python:3.13-bookworm`
- Node via NodeSource (22.x) with npm configured to disable fund/update-notifier noise
- Global CLI pins (avoid `latest` drift):
  - `@anthropic-ai/claude-code@2.0.55`
  - `@openai/codex@0.63.0`
  - `@google/gemini-cli@0.18.4`
- Host Docker socket mounted (`/var/run/docker.sock`) to enable Docker-in-Docker workflows
- Post-create step installs pip, uv, and project deps from `docker/pyproject.toml` (dev extras)
- Runs as root by default (no custom UID/GID)

Security note: In light of recent npm supply-chain incidents (e.g., “Shai-Hulud”), CLI deps are pinned explicitly rather than using `latest`. The repo’s JS deps are minimal (Tailwind) and do not include affected packages, but keep an eye on advisories and avoid pulling unpinned, newly compromised versions.
