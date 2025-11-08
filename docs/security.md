# Security Considerations

## Threat Model Snapshot

| Vector | Mitigations | Residual Risk |
| --- | --- | --- |
| Vault or runtime access | Single-user deployment, private hosting, OS permissions | If someone reaches your filesystem, prompt injection is no longer the main threat |
| Web content ingestion | Tool-level safety instructions, Tavily pre-processing, validation scenarios | Hidden payloads may surface if future tools bypass Tavily or directives are ignored |
| Code execution tool | Network-isolated sandbox, no outbound requests allowed | Malicious code cannot exfiltrate data or fetch new content |


## Philosophy

AssistantMD is designed as a **single-user application** running on your local machine or private server. There is no cross-user contamination or shared data.

**Primary security concerns:**
- User error when configuring assistants
- Exposure risks if you make the API or chat UI publicly accessible on the internet


## Application Exposure

AssistantMD ships without built-in authentication, access control, or transport encryption. The deployment model assumes you run the API and UI inside a trusted network.

- **Local usage**: If you keep the container on your own machine, the operating system and physical access controls are your security boundary. Anyone who can reach `http://localhost:8000` has full control over the API and chat UI.
- **Remote access**: If you expose the service beyond your local machine, you must layer security yourself (for example, reverse proxy with TLS and authentication, VPN, or SSH tunnel). Without those controls, every endpoint—including configuration edits and environment-variable updates—is wide open on the network.
- **Data in transit**: Requests are plain HTTP by default. Use a reverse proxy or tunnelling solution to terminate TLS if you need encrypted traffic.

Keep these constraints in mind before putting the application on a public interface.

## Prompt Injection

### The Risk

When AI models process web content using tools like search, extract or crawl, malicious web pages may contain text designed to override the model's instructions. Crawling a test site with a "malicious prompt" embedded directly in the page's content successfully influenced smaller models.

**Potential impact:**
- Creation of incorrect or misleading content in your vault files
- If using `file_ops_unsafe`: possible deletion or modification of files within the vault

### Mitigation

**1. All web tools include security instructions**
- Models are explicitly told to treat web content as untrusted data
- Instructed to maintain focus on their task and report suspicious manipulation attempts
- This successfully innoculated the smaller models which had previously failed testing.

**2. Tavily reduces exposure to hidden content**
- Current testing suggests Tavily omits or sanitizes hidden CSS text, meta tags, and JSON-LD payloads before the model sees them
- Treat this as an additional layer, not a guarantee—future tool changes or alternate fetch paths may surface the payloads

**3. No data exfiltration possible**
- The `code_execution` tool runs inside a network-isolated sandbox
- No workflow tool can send data to external servers or download additional content
- Even if a model is compromised, your data stays local

**4. Continuous validation**
- `validation/scenarios/prompt_injection_security.py` exercises each vector (sr-only, JSON-LD, metas, noscript, a11y, crawl)
- Scenarios emit artifacts tracking whether any `INJECTED_*` token reaches assistant outputs

### Best Practices

- **Review outputs** from assistants that process web content
- **Use `file_ops_safe` by default** - only enable `file_ops_unsafe` when you need write/delete capabilities
- **Be cautious** when combining `file_ops_unsafe` with web tools on untrusted websites, and review every run
- **Keep backups** of important vault data (use git or another version control system)

## Environment Security

- Store API keys in the built-in secrets store (`system/secrets.yaml`). The file is ignored by git—keep it that way.
- Use access controls (disk permissions, encrypted backups) to protect both `system/` and your vaults.
- Limit who can access and modify assistant configurations.
- Review scheduled assistant outputs periodically.
