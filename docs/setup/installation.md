## Prerequisites
*   [Docker Engine](https://docs.docker.com/engine/install/) (Linux) or [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows, Mac)
*   An LLM endpoint (cloud API key or local model server)

⚠️  AssistantMD has **no built-in auth or TLS**. Run it on a trusted network and/or add your own security layers. See [security.md](docs/setup/security.md).

⚠️ It is strongly recommended that you back up your vaults before deploying for the first time, or create a test vault and then migrate the mount path when you have verified that everything works as expected.

⚠️ These instructions are optimized for installing on Linux. See the end of this document for notes for Windows and Mac. I have only tested installation on Linux and Windows.

### Create a folder for your deployment, structured as follows:
```
AssistantMD
├── system/
├── .env
└── docker-compose.yml
```
_Pre-creating the `system` folder is important to avoid a "permission denied" error. See the section below on file permission and customizing the runtime user._

Copy the contents of
`docker-compose.yml.example` into `docker-compose.yml`.

```bash
mkdir AssistantMD
cd AssistantMD
mkdir system
nano docker-compose.yml
```
_Or alternate text editor if you don't have nano._

Create the installation encryption key in `.env` before starting AssistantMD.
On Linux with OpenSSL installed, run:

```bash
openssl rand -base64 32 | tr '+/' '-_' | tr -d '='
```

Copy the generated value into `.env`:

```text
ASSISTANTMD_SECRETS_KEY=PASTE_GENERATED_KEY_HERE
```

Keep `.env` separate from `system/secrets.db` backups. If `.env` is lost,
AssistantMD can still start and display system diagnostics, but providers and
models remain unavailable until the matching key is restored or encrypted
credentials are reset and re-entered. AssistantMD does not provide key export
or managed key backup.

For an installation reached through a reverse proxy, also add the externally
visible AssistantMD origin to `.env`:

```bash
printf '%s\n' 'ASSISTANTMD_PUBLIC_URL=https://assistant.example.com' >> .env
```

Use the exact origin shown in the browser: scheme, hostname, and optional port,
with no application path or callback path. Do not use the container address,
proxy upstream such as `http://127.0.0.1:8000`, or an apex domain when
AssistantMD actually runs on a subdomain. Plain HTTP is accepted only for
localhost and loopback development addresses. Existing local installations may
leave this unset; browser callback origins are then inferred where supported.

Choose one ingress-authentication mode in `docker-compose.yml`:

```yaml
environment:
  - ASSISTANTMD_AUTH_MODE=disabled
```

The default Compose example publishes the port only on host loopback, but
AssistantMD itself is unprotected in `disabled` mode. Every peer that can route
to the container receives full UI and API access, and the System tab displays a
persistent warning. Use this combination only when host access and Docker
network membership are acceptable security boundaries.

Do not select application `loopback` mode for a normal bridged container.
Docker-forwarded requests arrive from a bridge peer rather than `127.0.0.1` or
`::1`, even when the published host port is bound to loopback. `loopback` mode
is for direct-process or compatible host-network deployments where AssistantMD
observes the caller as an actual loopback socket peer.

For built-in owner authentication, generate a high-entropy token into a file
that is not committed:

```bash
mkdir -p secrets
openssl rand -hex 32 > secrets/assistantmd-auth
chmod 600 secrets/assistantmd-auth
```

Mount it read-only and select `owner_token`:

```yaml
services:
  assistant:
    environment:
      - ASSISTANTMD_AUTH_MODE=owner_token
      - ASSISTANTMD_AUTH_SECRET_FILE=/run/secrets/assistantmd-auth
    volumes:
      - ./secrets/assistantmd-auth:/run/secrets/assistantmd-auth:ro
```

For an existing authenticating reverse proxy, select `trusted_proxy` with the
same secret-file mount, optionally add
`ASSISTANTMD_AUTH_TRUSTED_PROXY_NETWORKS`, and have the proxy remove any inbound
`X-AssistantMD-Proxy-Assertion` header before setting that header to the secret
value on the upstream request. Do not mount the authentication secret into an
advanced-shell container. See [Security Considerations](security.md) for
the mode contracts and ingress limits.

### Open `docker-compose.yml` and update the following:

- Replace `/absolute/path/to/your/vaults` with the directory that holds your
  vault folders. The app will look for subfolders inside `/absolute/path/to/your/vaults` and treat them as vaults. See examples below.
- If you have directories in that path that should not be treated as vaults, create a `.vaultignore` file in the directory and it will be ignored.
- **Do not** change the right hand side: `/app/data` or the `./system:/app/system` mount.
- Set `TZ` to your local [timezone](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones) so that scheduled workflows run when you expect them to.
- Keep the `env_file: .env` entry so the container receives the installation
  encryption key and optional canonical public URL.

**Optional**
- Change the host side (the left side) of `127.0.0.1:8000:8000` if you want to expose the UI on a different IP/port (e.g. `192.168.0.1:1234:8000`).
- Set `ASSISTANTMD_IMAGE_TAG` in `.env` to lock both AssistantMD and its optional
  advanced shell to the same release. See the
  [repository](https://github.com/DodgyBadger/AssistantMD/tags) for available
  tags.


### Start the System
`docker compose up -d`

**Verify Installation**
`docker ps` should show assistantMD running. If you see "restarting", something is wrong. Run `docker logs assistantMD` to check for startup errors.

### Advanced shell infrastructure

Advanced shell configuration is deployment-owned and read when AssistantMD
starts. Restricted mode is the default. The optional `advanced` Compose profile
starts a version-matched advanced shell on the private Compose network without
publishing SSH to the host.

Add the following to `.env`:

```dotenv
COMPOSE_PROFILES=advanced
ASSISTANTMD_EXECUTION_MODE=advanced
```

Start or recreate the deployment:

```bash
docker compose up -d
```

On first start, AssistantMD and the advanced shell generate their own SSH identities
and exchange only public keys through narrowly scoped Docker volumes. The keys
are disposable deployment state: users do not need to generate, inspect, or
back them up. Normal container recreation preserves them. Removing all four
advanced-shell identity/public-key volumes and recreating both services creates
a new pairing without affecting AssistantMD data or encrypted credentials.

The supplied service defaults normally require no additional endpoint settings:

```dotenv
ASSISTANTMD_SHELL_HOST=assistantmd-shell
ASSISTANTMD_SHELL_PORT=2222
ASSISTANTMD_SHELL_USER=assistantmd-shell
```

Set these only when an equivalent deployment uses a different service name,
network alias, port, or user. Identity paths are fixed internal infrastructure,
are not `.env` settings, and must not be shared between the two containers.

By default, the advanced shell sees only its persistent home and workspace volumes.
It does not see AssistantMD vaults. Optional bind-mount examples are provided in
`docker-compose.override.yml.example`. Pre-create every selected host path and
prefer read-only vault mounts. Never mount AssistantMD's `system/` directory,
the Docker socket, a home directory, or a host root.

Open System → Infrastructure after startup. Advanced mode is usable when the
advanced shell reports `ready`.

#### Development from a containerized checkout

For the persistent development advanced shell used by contributors, run:

```bash
scripts/start_advanced_shell_development.sh
```

That harness builds from the checkout and publishes SSH to host loopback by
default, which is correct when AssistantMD runs directly on that host. When
AssistantMD itself runs in a development container, select a host address
reachable from that container and deliberately publish the development port on
the required host interfaces, for example:

The development script binds SSH to host loopback by default, which is correct
when AssistantMD runs directly on that host. When AssistantMD itself runs in a
development container, select a host address reachable from that container and
deliberately publish the development port on the required host interfaces, for
example:

```bash
ADVANCED_SHELL_BIND_ADDRESS=0.0.0.0 \
ADVANCED_SHELL_CLIENT_HOST=<docker-host-gateway-address> \
scripts/start_advanced_shell_development.sh
```

This development publication may expose the SSH port beyond the local host;
restrict it with the host firewall and do not use it as the supported private
Compose topology.

Access the web interface at `http://localhost:8000/` (or whichever host IP/port
you configured in the compose file). Open the **System** tab and configure at
least one model provider. Changes apply immediately—no container restart
required.

For OpenAI chat models, the stable setup is still to add `OPENAI_API_KEY` under
**Secrets**. AssistantMD also includes an experimental OpenAI OAuth option for
the built-in OpenAI provider. To use it, enable OpenAI OAuth in **System →
Application Settings**, allow editing for the built-in `openai` provider if
needed, then use the provider panel to connect with OAuth. Device-code login is
available for remote/server installs where the browser is not running on the
same machine as the container. API-key auth remains supported and is the
recommended fallback if OAuth is unavailable.

If you plan to enable the built-in nightly session summarization workflow,
configure `OPENAI_API_KEY` for the default `embeddings` model alias. OAuth is
for OpenAI chat model auth and does not replace the API key used by the current
embeddings setup.

To connect Gmail, create a Google OAuth 2.0 **Web application** client and add
the exact callback shown under **System → Connections → Built-in connections →
Google** to its authorized redirect URIs. Save that client ID and write-only
client secret in AssistantMD, then choose **Authorize Google**. The OAuth consent
screen must permit the account you use, and the Gmail API must be enabled for
the Google Cloud project. Gmail access is read-only. Google authorization
requires `ASSISTANTMD_PUBLIC_URL`; the displayed authorization URL can be copied
to another browser when the new tab cannot be opened automatically.

To add an MCP server, open **System → Connections → MCP connections**. Remote
servers use a Streamable HTTP or SSE endpoint. Advanced mode also supports
trusted stdio servers installed in the advanced shell. Ask chat to
follow the bundled **Advanced Shell MCP Setup** skill, then paste its YAML or JSON
block into the import box and review the resulting connection before adding and
testing it. Individual launch fields remain available for expert configuration.
Configure an exact-name tool allowlist when you do not intend to trust every
tool exposed by the server. Static bearer and custom-header credentials are
write-only and encrypted at rest.

Advanced-shell stdio registration never installs software. It launches the recorded
absolute executable through AssistantMD's fixed SSH pairing and can advertise
explicit `/workspace` or advanced-shell-home paths as MCP Roots. Its environment
field is non-secret. Use HTTP/SSE for any provider requiring credentials managed
by AssistantMD.

For OAuth servers, save any pre-registered client ID, client secret, or explicit
scopes required by the server, then choose **Authorize**. Servers advertising
dynamic client registration do not require those client fields. AssistantMD
shows the authorization URL for headless use and supports a pasted callback URL
when automatic completion is unavailable. A configured
`ASSISTANTMD_PUBLIC_URL` provides the stable callback origin.

Remote MCP endpoints require HTTPS. For a trusted server on a private network,
including a Docker service reachable by container name, enable **Allow HTTP on
a private network** on that connection. HTTP traffic and credentials are not
encrypted in transit. Public plaintext MCP endpoints remain rejected.

When you run AssistantMD, it adds an `AssistantMD/` folder to each mounted vault:

- `AssistantMD/Skills/` — reusable procedures the agent can follow
- `AssistantMD/Authoring/` — workflow and context assembly scripts
- `AssistantMD/Chat_Sessions/` — exported chat transcripts
- `AssistantMD/Import/` — drop PDFs and images here to import to markdown

The default setup also looks for optional files such as `AssistantMD/soul.md`, `AssistantMD/playbook.md`, and `AssistantMD/user.md`.

See [How to Build with AssistantMD](../use/build-guide.md) for details on how
these files, skills, workflows, context assembly, and session summaries fit
together.

## Optional Setup

## Integrations

**Web search**: The default web search tool uses the free duckduckgo library. This is enabled by default. To enable more advanced searches, web extraction and web crawling, you can add a [Tavily API key](https://www.tavily.com). The free tier will be sufficient for many users and is worth grabbing.

**Browser tool**: The built-in browser tool requires the Playwright Chromium runtime in addition to the Python package. The published container image includes this. If you build your own image from source, rebuild after pulling the latest Dockerfile changes so the image runs `python -m playwright install --no-shell chromium` during the build.

The standard browser-capable profile requires at least 2 GB of memory available
to AssistantMD and defaults to one active Chromium session. On an approximately
1 GB host or container, use the lightweight profile by adding `browser` to
`disabled_tools`; `web_extract` remains available for ordinary static pages.
Docker's memory limit, memory reservation, and `shm_size` are separate controls,
and a 2 GB container limit cannot provide memory that the host does not have.

If the container exits during browser-heavy work without an AssistantMD or
Logfire terminal event, inspect `docker inspect` for `OOMKilled` and the restart
count. A kernel OOM kill can terminate the process before in-process logs flush.

**Logfire**: AssistantMD uses the logfire library for rich console logging (what you see if you run `docker logs assistantmd`). You can add a [Logfire API key](https://pydantic.dev) to get even more data including full details of every LLM call. The free tier will be sufficient for many users and is worth grabbing. Be sure to also set logfire=true in the System tab of the web interface.


### File permission and customizing the runtime user

**Linux:** The default docker image runs as UID 1000 inside the container. This is the most common non-root user ID on Linux systems. It ensures that markdown files edited or written by the app remain accessible to you on the host. If it ran as root inside the container, you would lose access to any markdown files it touched. This works in reverse also. If the volumes being mounted into the container (`/absolute/path/to/your/vaults` and `./system`) are created by root on the host (i.e. you let docker create them or use `sudo`), then UID 1000 inside the container will not have access.

If you see "permission denied" in the docker logs when loading the app, first make sure that your user on the host is UID 1000 by running `id` in the terminal. Then make sure that the two mounted folders are not owned by root. 

If your UID is not 1000, then you need to build a custom image. There are also scenarios where you might want to run as root inside the container, such as hosting AssistantMD and syncing your markdown files to a remote server.

Clone the repo:
`git clone https://github.com/DodgyBadger/AssistantMD.git`

Rename both docker compose files

```bash
cd AssistantMD
cp docker-compose.yml.example docker-compose.yml
cp docker-compose.override.yml.example docker-compose.override.yml
```

Edit docker-compose.yml as above.
In docker-compose.override.yml, edit `build.args` and `user` as needed. E.g.

```
    args:
      USER_ID: 1001
      GROUP_ID: 1001
  user: "1001:1001"
```

Build and run the image: `docker compose up -d --build`

**Windows & Mac:** On Windows and Mac, you will most likely be using Docker Desktop and file permissions should not be an issue. Docker Desktop runs Docker inside a Linux VM and then maps file permissions between the VM and the host. I have tested this on Windows but not on Mac. If you get permission errors on a Mac, then try following the instructions above to build with a different UID (often 501). Run `id` in a terminal to verify.


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

## Additional Notes

**Windows:** Recommended to set up the compose file in WSL and use a Linux path to your vaults on the Windows host (look in `/mnt`).

**Mac:** Should work the same as Linux, but I have not tested.

**All:** If your vault path has spaces or other special characteres, wrap the whole line in double quotes.
```
    volumes:
      - "/absolute/path/to/your/vaults:/app/data"
      - ./system:/app/system              
```

**Local LLMs (general guidance)**: If running your local LM server on bare metal (for example LM Studio), change the settings to serve on local network so you get a host IP and not `127.0.0.1`. Localhost will not be reachable from inside the AssistantMD container without additional Docker networking customization. The `base_url` should look like `http://<host-lan-ip>:1234/v1` (for example `http://192.168.1.42:1234/v1`). If running your local LM server inside a Docker container, make sure AssistantMD and the LM server are on the same Docker network and use the Docker service name as the `base_url`, for example `http://lmstudio:1234/v1`.
