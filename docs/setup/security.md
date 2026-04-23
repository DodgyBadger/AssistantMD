# Security Considerations

## Philosophy

AssistantMD is designed as a **single-user application** running on your local machine or private server.


## Application Exposure

**AssistantMD does not include built-in authentication, access control, or transport encryption.** The deployment model assumes you run the API and UI inside a trusted network.

- **Local usage**: If you run the container on your own machine, the operating system and physical access controls are your security boundary. Anyone who can reach `http://localhost:8000` has full control over the API and chat UI.
- **Remote access**: If you expose the service beyond your local machine, you must layer security yourself (for example, reverse proxy with TLS and authentication, VPN, or SSH tunnel). Without those controls, every endpoint — including secrets and settings updates — is exposed.
- **Data in transit**: Requests are plain HTTP by default. Use a reverse proxy or tunnelling solution to terminate TLS if you need encrypted traffic.

Keep these constraints in mind before putting the application on a public interface.

## Prompt Injection

### The Risk

When AI models process web content using tools like search, extract or crawl, malicious web pages may contain text designed to override the model's instructions. Crawling a test site with a "malicious prompt" embedded directly in the page's content successfully influenced smaller models.

**Potential impact:**
- Creation of incorrect or misleading content in your vault files
- If using `file_ops_unsafe` tool, possible deletion or modification of files within the vault

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
- The `browser` tool is restricted to public-network, read-oriented requests and cannot upload files or initiate downloads.
- Residual risk still exists wherever the application is intentionally configured to communicate with external providers or websites.

### Best Practices

- Review outputs from workflows and context templates that process web content
- Use `file_ops_safe` tool by default - only enable `file_ops_unsafe` when you need write/delete capabilities
- Be especially cautious when combining `file_ops_unsafe` with `browser` or other web tools on untrusted websites
- Prefer the least powerful web tool that can do the job:
  - search when you need discovery
  - extract when you already know the page URL
  - browser only when simpler web retrieval is insufficient
- For browser usage, start with a single extraction pass before attempting narrower selectors or follow-up actions
- Test prompt-injection-sensitive workflows before trusting them with write/delete capabilities
- Keep backups of important vault data
- API keys are kept in the built-in secrets store (`system/secrets.yaml`). The file is ignored by git - keep it that way.
