## Upgrading

⚠️ Beta software. Check the
[release notes](https://github.com/DodgyBadger/AssistantMD/releases/latest) before
upgrading.

### Upgrading to v0.8.0

1. Back up your vaults, `system/`, and `.env`. Keep the `.env` backup separate
   because it contains the key needed to read encrypted credentials.

2. If the deployment does not have `.env`, copy `.env.example`, then follow
   [Configure `.env`](installation.md#4-configure-env) to add a new
   `ASSISTANTMD_SECRETS_KEY`, timezone, and authentication mode. Existing OAuth
   accounts must be reconnected after the upgrade.

3. Replace `docker-compose.yml` with the current
   [`docker-compose.yml.example`](../../docker-compose.yml.example), then restore
   only your vault path, system path, and deliberate resource overrides. Keep
   user-configurable values in `.env`.

4. If you want advanced mode, add these values to `.env`; otherwise leave them
   unset:

   ```dotenv
   COMPOSE_PROFILES=advanced
   ASSISTANTMD_EXECUTION_MODE=advanced
   ```

5. Pull and restart the deployment:

   ```bash
   docker compose down
   docker compose pull
   docker compose up -d
   ```

   For a repository build, run `git pull` and replace the pull command with
   `docker compose build`.

6. Open **System → Infrastructure** and confirm the expected authentication and
   execution modes. Advanced mode is ready when the advanced shell reports
   `ready`.

On first v0.8.0 startup, AssistantMD migrates legacy static secrets into encrypted
storage and keeps the old file at `system/migration_backups/secrets.yaml.bak`.
Routine `docker compose down` preserves advanced-shell pairing, installed files,
and workspace data. Do not add `-v` unless you deliberately want to delete those
Docker volumes.
