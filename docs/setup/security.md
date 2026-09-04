# Security Considerations

## Philosophy

AssistantMD is designed as a **single-user application** running on your local machine or private server.


## Application Exposure

AssistantMD requires an explicit ingress-authentication mode:

- `loopback` is for direct host-process runs, primarily development through
  `scripts/dev run`. It admits only an actual `127.0.0.1` or `::1` socket peer
  and provides no login. It is not applicable to the standard Docker Compose
  installation.
- `trusted_proxy` requires a secret assertion injected by an authenticating
  reverse proxy. It reuses the proxy's human login rather than adding another.
- `owner_token` provides a single-owner token exchange and signed HttpOnly
  browser session. Use HTTPS for every non-loopback deployment.
- `disabled` intentionally leaves the complete UI and API open to every
  routable peer, including advanced-shell containers. It is intended for recovery
  and deliberate testing and is not recommended for network-accessible use.

The selected mode authenticates requests as the current single-user
`local-user` principal. AssistantMD does not provide user registration,
password recovery, roles, or transport encryption.

For `trusted_proxy`, the proxy must remove any client-supplied assertion header
before inserting its own value. Keep the shared assertion outside browser
responses and outside the advanced-shell container. Configure a trusted immediate
proxy network as defense in depth where the deployment has stable addressing.
Only the authenticating proxy should be able to reach the AssistantMD upstream.
The [Installation Guide](installation.md#access-from-another-device) contains the
copyable proxy and Docker-network configuration.

For `owner_token`, store the credential in the deployment's protected `.env`
file and do not reuse the installation encryption key. The browser session lasts
up to 12 hours. Logout clears browser cookies but does not revoke a copied
stateless session; rotate the owner token to invalidate all outstanding sessions.

Application middleware rejects aggregate request headers over 64 KiB, but the
HTTP server receives headers before application code runs. Reverse proxies must
apply an equal or smaller header limit, authentication-failure rate limits, TLS,
and appropriate request-body limits at ingress.

For reverse-proxy deployments, configure `ASSISTANTMD_PUBLIC_URL` with the
externally visible HTTPS origin. This lets AssistantMD construct exact OAuth
callbacks without trusting request host or forwarded headers. It does not
configure DNS, TLS, authentication, or proxy routing; the proxy must still route
the callback path and satisfy the configured authentication mode.

Keep these constraints in mind before putting the application on a public interface.

## Advanced Shell

Advanced execution mode gives interactive chat a general, noninteractive shell
inside a separate persistent container. Commands may install and execute software,
read and write the advanced shell's home and workspace, and use outbound network
access unless the operator imposes additional network policy. Treat enabling this
mode as granting the model authority over everything made available to that
container.

The environment is intentionally constrained: commands run as a non-root user,
the base filesystem is read-only, tool calls have bounded execution, and the
container is not a systemd host or supported cron/service platform. Persistent
home and workspace volumes preserve files, not processes. Services that must run
continuously or restart autonomously should use a separately reviewed Compose
service with their own explicit privileges, mounts, network policy, and lifecycle.

Docker is the primary isolation boundary. The supplied service runs with a
read-only container filesystem, dedicated writable volumes, a PID and memory
limit, dropped capabilities except those required by OpenSSH, and
`no-new-privileges`. Preserve those controls. Never mount the Docker socket,
AssistantMD's `system/` directory, a host home or root directory, or other
administrative interfaces into the advanced shell.

AssistantMD and the advanced shell generate separate SSH identities and exchange
only public keys through one-way Docker volumes. AssistantMD pins the resulting
host identity, and the advanced shell accepts only the enrolled AssistantMD client.
This authenticates the fixed control channel; it does not make commands, packages,
MCP servers, or other software executed inside the advanced shell trustworthy.

AssistantMD's encrypted credentials, installation key, owner token, and trusted
proxy assertion are intentionally absent from the advanced shell. Do not mount or
copy them into it. In `disabled` authentication mode, every routable peer can use
the complete AssistantMD API; this includes the advanced-shell container because
it shares the Compose network. The authenticated modes prevent that access unless
their credential is separately disclosed.

Every bind mount expands the shell's authority:

- a read-only mount discloses all readable content beneath it;
- a writable mount also permits creation, modification, and deletion; and
- mount permissions are a deployment boundary, not an instruction the model can
  enforce for itself.

Credentials may be stored deliberately in the advanced shell for software that
needs them, but they are then readable and usable by chat through `shell`. Prefer
AssistantMD-managed encrypted credentials and normal MCP connections when the
server supports them. If a credential must live in the advanced shell, scope it
narrowly and accept that it belongs to the agent-accessible environment. Do not
paste credentials into chat or command arguments: shell tool calls and results are
part of chat history even though the separate activity log excludes command text,
stdin, stdout, and stderr.

Registering a stdio provider as an MCP connection keeps its disclosed tools inside
AssistantMD's tool allowlist and deferred tool-search path. Chat can instead start
or communicate with a process directly through `shell`, bypassing those MCP
discovery and allowlist controls. That escape hatch is inherent to general shell
access; use it deliberately and prefer a registered connection for ongoing use.

The current single-user deployment exposes one shared advanced shell only to the
initial `local-user` tenancy. It does not provide per-principal Unix accounts,
filesystems, processes, credentials, or resource isolation. A future multiuser
deployment must add an explicit isolation strategy before granting advanced-shell
access to mutually untrusted principals.

## Vault File Uploads

Vault Explorer uploads intentionally accept arbitrary file content because
vaults may contain PDFs, images, office documents, and other user-owned
artifacts. The upload boundary:

- requires an existing configured vault and a safe vault-relative destination;
- rejects absolute paths, `.`/`..` components, control characters, overlong
  paths, and paths that resolve through symlinks outside the selected vault;
- treats the multipart filename as display metadata only and uses the validated
  API path as the destination;
- accepts exactly one multipart file per request;
- enforces `vault_upload_max_mb_per_file` and never overwrites an existing
  destination; and
- writes through vault mutation history.

Uploaded content is not malware-scanned. AssistantMD does not execute uploaded
files or render unknown binary types inline, but explicitly importing an
untrusted PDF or image hands that content to the configured ingestion parser.
Keep parser dependencies current and only import documents you are willing to
process.

The application-level size check is not a substitute for an edge request-body
limit. In particular, a chunked multipart request may be spooled by the HTTP
stack before the application can reject its file bytes, and repeated
within-limit uploads can consume vault storage. Remote deployments should set
request-size, rate, and storage limits at the authenticated reverse proxy.

## Prompt Injection

### The Risk

When AI models process web content using tools like search, extract or crawl, malicious web pages may contain text designed to override the model's instructions. Crawling a test site with a "malicious prompt" embedded directly in the page's content successfully influenced smaller models.

**Potential impact:**
- Creation of incorrect or misleading content in your vault files
- A model with `file_write` enabled can delete or modify files within the vault

### Mitigation

**1. All web tools include security instructions**
- Models are explicitly told to treat web content as untrusted data
- Instructed to maintain focus on their task and report suspicious manipulation attempts
- This successfully innoculated the smaller models which had previously failed testing.

**2. Tavily reduces exposure to hidden content**
- Web searches, page extractions and site crawls that use Tavily are further protected by Tavily's firewall that blocks PII leakage, prompt injection, and malicious sources.

**3. Browser tool applies stricter runtime boundaries**
- The `browser` tool blocks downloads by default.
- The `browser` tool blocks local/private network targets.
- The `browser` tool blocks redirects and subrequests to local/private network targets.
- The `browser` tool allows only read-oriented HTTP methods (`GET`, `HEAD`).
- Browser state is isolated per call by default.
- Browser extraction tries to focus on the main content region instead of dumping the entire page when possible.

These controls reduce the blast radius, but they do **not** make browser-fetched content trusted. A browser can still render hostile page text that attempts to manipulate the model.

**4. External communication remains limited, not impossible**
- The built-in web and browser tools are constrained to narrow retrieval-oriented behavior rather than arbitrary outbound actions.
- `web_extract` and URL ingestion validate public-network targets at the initial
  URL and every redirect. Provider strategies are explicit and do not silently
  fall back to another network path.
- The `browser` tool is restricted to public-network, read-oriented requests and cannot upload files or initiate downloads.
- Residual risk still exists wherever the application is intentionally configured to communicate with external providers or websites.

### Best Practices

- Review outputs from workflows and context templates that process web content
- Disable `file_write` app-wide when a deployment should not permit model-driven vault mutations
- Use inline edit mode when you want to inspect interactive chat mutations before they execute
- Be especially cautious when combining `file_write` with `browser` or other web tools on untrusted websites
- Prefer the least powerful web tool that can do the job:
  - search when you need discovery
  - extract when you already know the page URL
  - browser only when simpler web retrieval is insufficient
- For browser usage, start with a single extraction pass before attempting narrower selectors or follow-up actions
- Test prompt-injection-sensitive workflows before trusting them with write/delete capabilities
- Keep backups of important vault data
- API keys and OpenAI OAuth token state are encrypted at rest in
  `system/secrets.db`. Protect and back up the installation key in `.env`
  separately; losing it requires re-entering stored credentials.
- Google OAuth client secrets, access tokens, refresh tokens, connected account
  identity, and pending authorization state are principal-owned and encrypted
  in `system/secrets.db` and scoped to a named Google connection. Google client
  IDs, display names, default selection, and Gmail capability preferences and
  limits are non-secret principal-owned connection metadata.
- Gmail tools are absent unless the active principal has the required scope.
  Treat every email header, body, attachment descriptor, and downloaded file as
  untrusted external data. Bounded PDF attachments may be written to a
  caller-selected vault path, but attachment bytes are never exposed to chat or
  logs. PDF format checks do not establish that a downloaded file is safe.
- MCP servers are trusted tool providers, not passive content sources. Enabling
  a connection permits the model to call every allowed server tool; AssistantMD
  cannot infer whether an MCP tool reads data or causes external side effects.
  Use exact allowlists, connect only servers you trust, and apply the same
  caution to unattended workflows.
- MCP definitions and OAuth/static credentials are principal-owned. Credentials
  and OAuth state are encrypted in `system/secrets.db`, while sanitized
  connection metadata is stored in `system/mcp.db`. Remote endpoints require
  HTTPS. Private-network HTTP requires explicit acknowledgement on each
  connection and never permits public plaintext endpoints.
