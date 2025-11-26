# Security Considerations

## Philosophy

AssistantMD is designed as a **single-user application** running on your local machine or private server. There is no cross-user contamination or shared data.

**Primary security concerns:**
- User error when configuring workflows
- Exposure risks if you make the API or chat UI publicly accessible on the internet


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
- Current testing suggests Tavily omits or sanitizes hidden CSS text, meta tags, and JSON-LD payloads before the model sees them
- Treat this as an additional layer, not a guarantee—future tool changes or alternate fetch paths may surface the payloads

**3. No data exfiltration possible**
- The `code_execution` tool uses Piston (public endpoint by default). The public instance is sandboxed for untrusted code, and you can self-host Piston for stricter network isolation if needed.
- No workflow tool can send data to external servers or download additional content beyond their providers.
- Even if a model is compromised, your data stays local

### Best Practices

- Review outputs from workflows that process web content
- Use `file_ops_safe` tool by default - only enable `file_ops_unsafe` when you need write/delete capabilities
- Be cautious when combining `file_ops_unsafe` with web tools on untrusted websites, and test your runs
- Keep backups of important vault data
- API keys are kept in the built-in secrets store (`system/secrets.yaml`). The file is ignored by git - keep it that way.
