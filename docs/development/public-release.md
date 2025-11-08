# Public Release Playbook

Use this checklist to migrate the project into a public GitHub repository with
reproducible Docker builds and CI/CD.

## Repository Bootstrap
1. Authenticate `gh` with the target org/user: `gh auth login`.
2. Create the public repo from the current working tree:
   ```bash
   gh repo create <org/AssistantMD> --public --source=. --remote=origin
   git push -u origin main
   git checkout -b dev
   git push -u origin dev
   git checkout main
   ```
3. Keep the legacy private repo read-only for archival purposes.

## Branch Protections
Configure protections for `main` and `dev`:
- Require pull requests with a linear history (squash or rebase merges).
- Require the `ci-validation` workflow to pass for both branches.
- Require at least one approval for `dev` PRs and two for `main`.
- Optionally require signed commits.

## Secrets & Variables
Add the following repository secrets before enabling workflows:
- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GEMINI_API_KEY`
- `MISTRAL_API_KEY`
- `TAVILY_API_KEY`
- `LIBRECHAT_API_KEY`
- `GHCR_PAT` (token with `write:packages` to push the release image)

The CI workflows call `python scripts/seed_ci_secrets.py` to overwrite
`system/secrets.yaml` from the environment, so any secret you configure becomes
available to the runtime without committing it to the repo.

Optional:
- `ENV_FILE` for base64-encoded `.env` exports if a one-shot import is useful.
- Environment-specific secrets for staging/production deployments.

## CI Workflows
- `.github/workflows/validation.yml` (`ci-validation`) runs on push/PR to
  `main` and `dev`. It installs dependencies with `uv`, runs the entire
  `integration/` scenario folder, and uploads artifacts from `validation/runs/`.
- `.github/workflows/release.yml` triggers on `v*` tags. It reuses the same
  validation runner, exports release notes via `scripts/export_changelog.py`,
  builds a multi-arch Docker image from `docker/Dockerfile`, pushes it to GHCR,
  and publishes a GitHub Release that includes `changelog.md`.

## Validation Suite
CI executes every scenario in `validation/scenarios/integration/`, which
currently includes:
- `basic_haiku`
- `system_startup_validation`
- `api_endpoints`
- `tool_suite`

Drop any scenario you do not need from that folder (or add new ones) and the
workflows automatically follow suit.

## Release Flow
1. Update version metadata and changelog entries.
2. Export the changelog and the latest entry:
   ```bash
   python scripts/export_changelog.py \
     --output changelog.md \
     --latest-output release-notes.md
   ```
3. Open a release PR from `dev` → `main`. Merge after `ci-validation` passes.
4. Tag the merge commit with `vMAJOR.MINOR.PATCH` and push the tag:
   ```bash
   git tag v1.2.3
   git push origin v1.2.3
   ```
5. Monitor the `release` workflow. It will publish the GHCR image at
   `ghcr.io/<org>/<repo>:vX.Y.Z` and `:latest`, upload validation artifacts, and
   create the GitHub Release using `release-notes.md`.

## Post-Setup Verification
- Trigger the workflows manually via `gh workflow run` to ensure secrets are
  wired correctly.
- Attempt a direct push to `main` or `dev` to confirm protections block it.
- After the first tagged release, verify the GHCR package exists and that
  `docker pull ghcr.io/<org>/<repo>:latest` succeeds.
- Document these steps for contributors (link this file from `README.md`).
