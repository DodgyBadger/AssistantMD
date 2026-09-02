## Upgrading

⚠️ Beta software. Check the
[release notes](https://github.com/DodgyBadger/AssistantMD/releases/latest) before
upgrading.

### Upgrading to v0.8.0

1. Back up your vaults, `system/`, `.env`, and current Compose files. Keep the
   `.env` backup separate because it contains the key needed to read encrypted
   credentials.

2. v0.8 tracks `docker-compose.yml` so later pulls automatically receive
   required topology changes. In an existing repository checkout, preserve your
   old local file before pulling:

   ```bash
   mv docker-compose.yml docker-compose.pre-v0.8.yml
   git pull --ff-only
   ```

   Do not copy the old file back over the new tracked `docker-compose.yml`.

3. Copy `.env.example` to `.env` if needed. Preserve an existing encryption key;
   otherwise follow [Configure `.env`](installation.md#4-configure-env) to
   generate one. Move the old Compose values into `.env`:

   ```dotenv
   ASSISTANTMD_DATA_PATH=/old/host/path/previously-mounted-at-app-data
   ASSISTANTMD_SYSTEM_PATH=/old/host/path/previously-mounted-at-app-system
   ```

   Also preserve the timezone, authentication mode, authentication secret, and
   public URL appropriate to the deployment. Existing OAuth accounts must be
   reconnected when introducing a new encryption key.

4. Move structural customizations—custom builds or UID/GID, external proxy
   networks, and extra bind mounts—into `docker-compose.override.yml`. Start
   from `docker-compose.override.yml.example` and copy only the sections you
   need. Do not edit the tracked `docker-compose.yml`.

5. If you want advanced mode, add these values to `.env`; otherwise leave them
   unset:

   ```dotenv
   COMPOSE_PROFILES=advanced
   ASSISTANTMD_EXECUTION_MODE=advanced
   ```

6. Validate and restart the deployment:

   ```bash
   docker compose config --quiet
   docker compose down
   docker compose pull
   docker compose up -d
   ```

   For a repository build using the override example, replace
   `docker compose pull` with `docker compose build`. The override builds both
   AssistantMD and the advanced shell from the same checkout when the
   `advanced` profile is active.

7. Open **System → Infrastructure** and confirm the expected authentication and
   execution modes. Advanced mode is ready when the advanced shell reports
   `ready`.

On first v0.8.0 startup, AssistantMD migrates legacy static secrets into encrypted
storage and keeps the old file at `system/migration_backups/secrets.yaml.bak`.
Routine `docker compose down` preserves advanced-shell pairing, installed files,
and workspace data. Do not add `-v` unless you deliberately want to delete those
Docker volumes.
