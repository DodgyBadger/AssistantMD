# Browser Tool Follow-Ups

## Current Status

- `browser` exists as a Playwright-backed extraction tool.
- Search -> `tavily_extract` -> `browser` escalation guidance lives in tool instructions.
- Downloads are blocked by default.
- Private/local network targets are blocked.
- Large browser output now flows through normal tool routing, so auto-buffering can apply.
- Selector churn has been reduced with stronger instructions and clearer failure messages.

## Remaining Work

### Policy

- Decide the explicit trust model for browser-fetched content.
- Confirm hard invariants for browser usage:
  - downloads remain blocked
  - private/local network access remains blocked
  - no persistent browser session state by default
  - no automatic write/destructive follow-up actions based solely on web content
- Decide whether any additional redirect policy is needed for public URL -> private IP transitions.
- Decide whether `data:` URLs should remain allowed outside testing scenarios.
- Decide whether robots/site-policy considerations should affect browser use, even if the page is technically reachable.

### Settings

Candidate user-controlled settings:

- `browser_enabled`
- `browser_navigation_timeout_seconds`
- `browser_selector_timeout_seconds`
- `browser_allow_data_urls`

Candidate internal-only policy controls:

- block downloads
- block private/local network targets
- isolate browser state per call

### Extraction Quality

- Keep evaluating whether the generic content-root fallback is broadly helpful.
- Do not add site-specific selector hacks unless repeated cross-site evidence justifies a more general rule.
- Watch for pages where `body` or large mixed-content containers still dominate first-pass extraction.

### Validation

- Add/extend validation coverage for:
  - oversized browser output routing to buffer
  - blocked download URL behavior
  - bad selector guidance
  - private/local network blocking
  - browser-specific prompt injection resistance

### Security Testing

- Update the existing prompt injection security scenario to include `browser` coverage.
- Measure how resistant browser-driven extraction is when the extracted content contains hostile instructions.
- Validate both:
  - whether tool instructions are strong enough to make the model treat browser results as untrusted data
  - whether any extraction choices materially reduce exposure to injected content
- Include at least one case where broad extraction surfaces the malicious text, so the test exercises the real instruction boundary rather than relying on accidental filtering.

## Open Questions

- Do we want a dedicated `http_fetch` tool for JSON/API endpoints instead of relying on browser/import paths?
- Should browser output include more structured metadata to help the model decide whether to retry?
- Is there any global instruction needed, or should web-priority guidance remain entirely in tool instructions?

## Working Position

- Keep web-priority guidance in tool instructions, not base chat instructions.
- Treat policy boundaries as hardcoded safety rules unless there is a strong reason to expose them as settings.
- Prefer broad heuristics over site-specific tuning.
