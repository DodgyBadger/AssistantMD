## Upgrading

⚠️ Beta software. Always check the [release notes](https://github.com/DodgyBadger/AssistantMD/releases/latest) for breaking changes.  
⚠️ Back up your notes and the `AssistantMD/system` folder.

### Upgrading to v0.8.0

Before replacing the running container, follow the v0.8.0
[installation-key setup](installation.md#create-a-folder-for-your-deployment-structured-as-follows)
to create `.env`, then add that file to the AssistantMD service in
`docker-compose.yml`:

```yaml
services:
  assistant:
    env_file:
      - .env
```

Docker Compose reads `.env` for variable substitution but does not otherwise
pass its values to the container. The `env_file` entry is therefore required
for AssistantMD to receive the encryption key and optional
`ASSISTANTMD_PUBLIC_URL`.

Back up `.env` separately from `system/`. On successful startup, AssistantMD
migrates static secrets into the encrypted database and preserves the old file
as `system/migration_backups/secrets.yaml.bak`. Existing OAuth accounts must be
reconnected.

Update `docker-compose.yml` from the current
[`docker-compose.yml.example`](../../docker-compose.yml.example), preserving
your vault path, system path, timezone, authentication choice, and any deliberate
resource overrides. The current Compose contract adds the optional
`advanced-shell` service and its named pairing/workspace volumes. AssistantMD
also mounts its side of the pairing volumes, even when restricted mode remains
selected.

Choose and configure an ingress-authentication mode before exposing the upgraded
application. The available modes are `owner_token`, `trusted_proxy`, `loopback`,
and deliberately unprotected `disabled`; see
[Security Considerations](security.md#application-exposure). Existing remote
deployments should not assume that a loopback host port protects access through a
reverse proxy or shared Docker network.

To enable the advanced shell, add the following to `.env`:

```dotenv
COMPOSE_PROFILES=advanced
ASSISTANTMD_EXECUTION_MODE=advanced
```

Restricted deployments should leave both settings unset. The advanced shell's
SSH identities are disposable named-volume state and do not belong in backups.
Preserving the named volumes retains the pairing across ordinary image upgrades.
Do not use `docker compose down -v` during a routine upgrade because it removes
the pairing as well as the advanced shell's persistent home and workspace.

***If you are using the default docker image:***
```bash
docker compose down
docker compose pull
docker compose up -d
```

When `COMPOSE_PROFILES=advanced` is set, these commands pull and recreate both
version-matched images. Keep `ASSISTANTMD_IMAGE_TAG` identical for AssistantMD
and the advanced shell; the supplied Compose file applies the one setting to
both.

***If you cloned the repo and built a custom image:***
```bash
docker compose down
git pull
docker compose up -d --build
```

After startup, open **System → Infrastructure**. Confirm the expected
authentication and execution modes. Advanced deployments are ready when
**Advanced shell readiness** reports `ready`; if it does not, recreate both
services together and inspect their logs without deleting the named volumes.
