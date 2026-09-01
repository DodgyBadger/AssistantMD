# Installation

The recommended installation uses Docker Compose and keeps deployment settings
in one `.env` file.

## 1. Install the prerequisites

You need:

- [Docker Engine](https://docs.docker.com/engine/install/) on Linux or
  [Docker Desktop](https://www.docker.com/products/docker-desktop/) on Windows
  or macOS; and
- access to a cloud or local language model.

Back up an existing vault before mounting it, or begin with a test vault.

## 2. Create the deployment folder

Create this layout:

```text
AssistantMD/
├── system/
├── .env
└── docker-compose.yml
```

Copy the repository's `.env.example` to `.env` and
`docker-compose.yml.example` to `docker-compose.yml`. Pre-create `system/` so
Docker does not create it with the wrong ownership.

```bash
mkdir -p AssistantMD/system
cd AssistantMD
```

The two example files are available at
[`.env.example`](../../.env.example) and
[`docker-compose.yml.example`](../../docker-compose.yml.example).

## 3. Choose your vault folder

In `docker-compose.yml`, replace `/absolute/path/to/your/vaults` with the folder
that contains your vaults. Change only the left side of this mount:

```yaml
- /absolute/path/to/your/vaults:/app/data
```

Each direct subfolder becomes an AssistantMD vault. The examples later in this
guide show single-vault and multi-vault layouts.

## 4. Configure `.env`

Generate the required encryption key:

```bash
openssl rand -base64 32 | tr '+/' '-_' | tr -d '='
```

Put the result in `.env`, choose your timezone, and start with local-only access:

```dotenv
ASSISTANTMD_SECRETS_KEY=PASTE_GENERATED_KEY_HERE
TZ=UTC
ASSISTANTMD_AUTH_MODE=disabled
```

The supplied Compose file publishes AssistantMD only on the host's loopback
address. This is the simplest setup when you will open AssistantMD on the same
computer. `disabled` means there is no application login, so do not expose that
port to a network.

If you will access AssistantMD through a TLS reverse proxy, choose
`trusted_proxy` or `owner_token` instead. Follow
[Access from another device](#access-from-another-device) before starting it.

Keep `.env` safe and back it up separately from `system/`. You need both the
encryption key and `system/secrets.db` to restore stored credentials.
On Linux, restrict it with `chmod 600 .env`.

## 5. Start AssistantMD

```bash
docker compose up -d
```

## 6. Open AssistantMD

Open <http://127.0.0.1:8000/>. If it does not load, inspect the container log:

```bash
docker logs assistantMD
```

## 7. Configure a model provider

Open **System → Providers**, choose a provider, and add the requested API key
or endpoint. AssistantMD is now ready to use.

AssistantMD adds an `AssistantMD/` folder to each mounted vault for skills,
workflows, imported documents, and exported chats. See
[How to Build with AssistantMD](../use/build-guide.md) when you are ready to
customize how it works.

## Optional setup

### Access from another device

AssistantMD does not provide TLS. Remote access should use HTTPS and one of these
authentication options:

- `trusted_proxy` when an existing reverse proxy already authenticates users;
- `owner_token` when the reverse proxy provides TLS but not authentication.

Generate a second secret for authentication. Do not reuse
`ASSISTANTMD_SECRETS_KEY`:

```bash
openssl rand -hex 32
```

#### Built-in owner login

Add the following to `.env`:

```dotenv
ASSISTANTMD_AUTH_MODE=owner_token
ASSISTANTMD_AUTH_SECRET=PASTE_A_DIFFERENT_RANDOM_SECRET_HERE
ASSISTANTMD_PUBLIC_URL=https://assistant.example.com
```

Configure your TLS reverse proxy to forward requests to AssistantMD, then run
`docker compose up -d`. The first browser visit shows AssistantMD's owner login;
enter `ASSISTANTMD_AUTH_SECRET` there.

For example, a Caddy process running on the Docker host needs only:

```caddyfile
assistant.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

#### Existing authenticating proxy

Add the following to `.env`:

```dotenv
ASSISTANTMD_AUTH_MODE=trusted_proxy
ASSISTANTMD_AUTH_SECRET=PASTE_A_DIFFERENT_RANDOM_SECRET_HERE
ASSISTANTMD_PUBLIC_URL=https://assistant.example.com
```

Give the proxy process the same `ASSISTANTMD_AUTH_SECRET` through its own secure
environment configuration. Do not give the proxy AssistantMD's complete `.env`.
After the proxy's authentication handler, replace the assertion header before
forwarding the request. For Caddy:

```caddyfile
reverse_proxy assistant:8000 {
    header_up -X-AssistantMD-Proxy-Assertion
    header_up X-AssistantMD-Proxy-Assertion {$ASSISTANTMD_AUTH_SECRET}
}
```

This upstream assumes Caddy shares a Docker network with AssistantMD. Use
`127.0.0.1:8000` instead when Caddy runs directly on the Docker host.

Run `docker compose up -d`. AssistantMD now accepts requests carrying the
proxy-only assertion and does not show a second login.

#### Proxy in another Compose project

For either authentication mode, a containerized proxy must share a network with
AssistantMD. Attach AssistantMD to the proxy's external network without removing
its advanced-shell network:

```yaml
services:
  assistant:
    networks:
      - assistantmd_advanced_shell
      - caddy_default

networks:
  assistantmd_advanced_shell:
  caddy_default:
    external: true
```

Run `docker compose up -d` after changing the networks. Use `assistant:8000` as
the proxy upstream.

For either option, use the exact HTTPS origin shown in the browser for
`ASSISTANTMD_PUBLIC_URL`. See
[Security Considerations](security.md#application-exposure) for the mode risks,
proxy hardening, and deliberately unprotected `disabled` mode.

The `loopback` authentication mode is for direct development runs such as
`scripts/dev run`, where AssistantMD is a host process rather than a Docker
Compose service. It is not applicable to the standard Docker installation.

### Enable advanced mode

Add one setting to `.env`:

```dotenv
COMPOSE_PROFILES=advanced
```

This starts the optional container and tells AssistantMD to expose the capability.
Restart with `docker compose up -d`, then confirm **System → Infrastructure**
reports the advanced shell as `ready`.

Advanced mode provides a constrained, non-root Linux environment for interactive
chat. Files under `/home/advanced-shell` and `/workspace` survive ordinary
container restarts and upgrades. Processes and `/tmp` do not, and the container
does not provide systemd or a supported cron/service supervisor.

The advanced shell cannot see your vaults unless you explicitly add a mount.
Examples are available in `docker-compose.override.yml.example`; prefer read-only
mounts. Never mount AssistantMD's `system/` folder, the Docker socket, a host home
folder, or the host root. See [Security Considerations](security.md#advanced-shell)
before adding access or credentials.

Stdio MCP servers installed there are launched when AssistantMD needs them. Ask
chat to follow the bundled **Advanced Shell MCP Setup** skill, then review and
paste its generated YAML or JSON into **System → Connections**.

Contributor setup for running AssistantMD and its advanced shell from a checkout
belongs in the [Development Guide](development.md).

### Configure connections

Open **System → Connections** to add Gmail or MCP connections. The UI provides
the callback URLs and fields required by each connection.

For OpenAI, add an API key under **Secrets** or enable the experimental OAuth
option under **Application Settings**. Gmail setup begins from its connection
card. Remote MCP servers begin from **MCP connections**. Follow the prompts in
the UI, and consult [Security Considerations](security.md) before granting a
server credentials or broad tool access.

### Enable optional integrations

- Web search works without another key. Add a Tavily key under **Secrets** for
  Tavily-backed search, extraction, and crawling.
- The published image includes the browser runtime. Hosts should make at least
  2 GB available to AssistantMD when the browser tool is enabled.
- Logfire is optional. Add its key under **Secrets** and enable Logfire in
  **Application Settings** if you want remote diagnostics.

## File permissions on Linux

The published image runs as UID 1000. The host vault and `system/` folders must
be writable by that user. If logs report `permission denied`, check the folder
ownership first.

If your host user has another UID, clone the repository, copy
`docker-compose.override.yml.example` to `docker-compose.override.yml`, set its
`USER_ID`, `GROUP_ID`, and `user` values, then run:

```bash
docker compose up -d --build
```

Docker Desktop normally handles this mapping automatically on Windows and macOS.


## Vault Path Examples

```
/home/user/MyVaults/
├── Personal/
```
Docker compose volume mount reads: `/home/user/MyVaults:/app/data`.  
AssistantMD will see one vault called `Personal`.

```
/home/user/MyVaults/
├── Personal/
├── Work/
└── Family/

```
Docker compose volume mount reads: `/home/user/MyVaults:/app/data`.  
AssistantMD will see three vaults called `Personal`, `Work` and `Family`

## Platform notes

- On Windows, WSL paths under `/mnt` are usually the simplest vault mounts.
- Quote a volume entry when its host path contains spaces.
- A local model server must listen on an address reachable from the AssistantMD
  container. Use its LAN address when it runs on the host, or its service name
  when both applications share a Docker network.
