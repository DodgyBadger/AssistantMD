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

***If you are using the default docker image:***
```
docker compose down
docker compose pull
docker compose up -d
```

***If you cloned the repo and built a custom image:***
```
docker compose down
git pull
docker compose up -d --build
```
