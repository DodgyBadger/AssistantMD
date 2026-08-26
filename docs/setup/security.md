# Security Considerations

## Philosophy

AssistantMD is designed as a **single-user application** running on your local machine or private server.


## Application Exposure

**AssistantMD does not include built-in authentication, access control, or transport encryption.** The deployment model assumes you run the API and UI inside a trusted network.

- **Local usage**: If you run the container on your own machine, the operating system and physical access controls are your security boundary. Anyone who can reach `http://localhost:8000` has full control over the API and chat UI.
- **Remote access**: If you expose the service beyond your local machine, you must layer security yourself (for example, reverse proxy with TLS and authentication, VPN, or SSH tunnel). Without those controls, every endpoint — including secrets and settings updates — is exposed.
- **Data in transit**: Requests are plain HTTP by default. Use a reverse proxy or tunnelling solution to terminate TLS if you need encrypted traffic.

For reverse-proxy deployments, configure `ASSISTANTMD_PUBLIC_URL` with the
externally visible HTTPS origin. This lets AssistantMD construct exact OAuth
callbacks without trusting request host or forwarded headers. It does not
configure DNS, TLS, authentication, proxy routing, or access control; the proxy
must still route the callback path and protect the application.

Keep these constraints in mind before putting the application on a public interface.

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
  IDs, display names, default selection, and Gmail result limits are non-secret
  principal-owned connection metadata.
- Gmail tools are read-only and are absent unless the active principal has the
  required scope. Treat every email header and body as untrusted external data;
  attachment bytes are not exposed to chat.
- MCP servers are trusted tool providers, not passive content sources. Enabling
  a connection permits the model to call every allowed server tool; AssistantMD
  cannot infer whether an MCP tool reads data or causes external side effects.
  Use exact allowlists, connect only servers you trust, and apply the same
  caution to unattended workflows.
- MCP definitions and OAuth/static credentials are principal-owned. Credentials
  and OAuth state are encrypted in `system/secrets.db`, while sanitized
  connection metadata is stored in `system/mcp.db`. Remote endpoints require
  HTTPS; the local/private HTTP override is for controlled development networks
  and never permits public plaintext endpoints.
