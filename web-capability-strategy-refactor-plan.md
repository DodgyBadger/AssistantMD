# Web Capability Strategy Refactor Plan

## Status

Implemented and hardened. Focused validation passed on 2026-07-21; the broader
maintainer-owned validation suite remains pending.

## Goal

Replace provider-named web tools with stable `web_search`, `web_extract`, and
`web_crawl` capabilities whose implementations are selected explicitly through
string settings. Share URL transport and HTML extraction machinery with the
ingestion pipeline, improve failure observability, and prevent browser-heavy
agent runs from exhausting constrained installations.

This refactor should leave AssistantMD with a small model-facing tool surface
that can change providers without changing prompts, authoring scripts, or tool
contracts. It should also establish reusable web-document primitives for a
future agent-driven import capability.

## Current Problems

- The default tool set exposes DuckDuckGo search and browser extraction but not
  Tavily extraction, despite browser documentation describing itself as a
  fallback from Tavily. On installations without Tavily enabled, agents can
  overuse Chromium for ordinary page extraction.
- Provider identity is part of the tool name (`web_search_duckduckgo`,
  `web_search_tavily`, `tavily_extract`, and `tavily_crawl`). Switching providers
  therefore changes the model and authoring contract.
- Search, extraction, and crawl provider code each owns its own formatting,
  secret lookup, timeout behavior, and failure handling.
- URL ingestion already has a bounded curl fetcher and an HTML-to-Markdown
  extractor, but those implementations are ingestion-owned and cannot be reused
  cleanly by a model-facing extraction capability.
- The curl fetcher follows redirects internally and validates only the final
  transport metadata. It must not be exposed to an agent-facing tool until each
  initial and redirected target is checked against the shared public-network
  policy.
- Each browser call launches Chromium without a process-wide concurrency guard.
  Parallel calls can exceed a small container's memory limit, and current
  process RSS telemetry does not describe Chromium child or cgroup memory.
- The current shipped Compose example has a `2G` memory limit, a `1G`
  reservation, and a `1gb` shared-memory ceiling. These values have different
  meanings: neither the reservation nor `shm_size` is a 1 GB container memory
  cap. Older deployments and 1 GB hosts may still provide only about 1 GB of
  total memory, which is not a reliable browser-capable operating profile.

## Architectural Decisions

### Stable Capabilities, Explicit Strategies

Expose exactly these provider-neutral model-facing tools:

- `web_search`
- `web_extract`
- `web_crawl`
- `browser`, retained as an explicit dynamic-page tool

Each web capability resolves one configured strategy. There is no automatic
provider fallback chain. A Tavily failure remains a Tavily failure; it must not
silently retry through curl, DuckDuckGo, or Chromium. The model may choose a
different explicit capability after receiving the failure, but infrastructure
does not change the configured strategy on its behalf.

Strategy names are opaque string identifiers in settings. Provider-specific
construction lives behind registries, so adding another implementation does not
change the settings schema or model-facing tool name.

Initial settings:

```yaml
web_search_strategy: duckduckgo
web_extract_strategy: curl
web_crawl_strategy: tavily
ingestion_url_fetch_strategy: curl
```

The three `web_*_strategy` settings control agent capabilities independently.
The ingestion setting remains independent so selecting Tavily for agent
extraction does not unexpectedly route all URL imports through Tavily. Both
paths resolve shared lower-level implementations where their strategies
overlap.

### Preserve Source and Extraction Boundaries

Keep ADR 0011's source-versus-extraction split:

- URL transport loads bytes and response provenance.
- HTML extraction converts a loaded document to Markdown.
- A built-in `curl` web-extract strategy composes those two stages.
- Ingestion adapters translate the shared transport and extraction results into
  `RawDocument` and `ExtractedDocument` without duplicating behavior.
- Tavily extraction remains a remote extraction strategy and does not pretend
  to be a raw URL transport.

Move the reusable pieces into a web subsystem rather than making tools call
ingestion or making ingestion call model-facing tools. The intended dependency
direction is:

```text
web tools --------> core/web service + strategy registry
                         |       |
ingestion adapters ----> transport and HTML extraction primitives
```

Use normalized result models for fetched resources, search results, extracted
documents, and crawled pages. Preserve source URL, effective URL, content type,
title, strategy ID, timing, status, and compact provider metadata. Do not put
full retrieved content in logs or failure metadata.

### Ingestion and Tool Ownership Boundary

The shared web subsystem owns only reusable retrieval and content-conversion
behavior. The two consumers retain distinct orchestration and policy:

| Concern | URL ingestion | `web_extract` |
| --- | --- | --- |
| Invocation | API or queued ingestion job | Agent tool call or Monty direct call |
| Input cardinality | One URL per durable job | One or more URLs per call |
| Strategy setting | Independent ingestion fetch strategy | `web_extract_strategy` |
| Shared work | URL validation, bounded fetch, response metadata, HTML-to-Markdown conversion | URL validation, bounded fetch, response metadata, HTML-to-Markdown conversion |
| Result | `RawDocument` then `ExtractedDocument` adapters | Normalized per-URL extraction results |
| Persistence | Job state, rendered Markdown, vault mutations, snapshots, activity | Chat/tool history and existing oversized-output cache only |
| Failure | Durable failed ingestion job and execution-task outcome | Structured model-visible tool failure |

Preserve the current URL-ingestion contract while replacing its duplicated
mechanics:

- `import_url_direct` still creates and processes a durable ingestion job.
- The per-request `clean_html` option still reaches HTML conversion through job
  `extractor_options`.
- URL ingestion still records the selected extraction strategy, warnings,
  source provenance, output paths, and terminal job status.
- Rendering, collision-safe output naming, frontmatter, storage, vault mutation
  tracking, and execution-task ownership remain in ingestion.
- Existing ordered extractor fallback for PDF and image ingestion is unaffected.
  The no-fallback decision applies to each new web capability's configured
  provider strategy, not to ingestion's established multi-strategy document
  extraction policy.
- Shared public-network URL policy applies to both consumers, so direct URL
  ingestion will also reject local/private initial targets and redirects. This
  closes an existing SSRF gap and is an intentional tightening of the import
  API contract.

The curl-backed `web_extract` strategy may compose the same fetch and HTML
conversion functions, but it must not enqueue ingestion jobs, render
frontmatter, write vault files, or inherit ingestion output naming. Conversely,
ingestion must not call a Pydantic AI tool adapter or receive model-formatted
text.

For multi-URL tool calls, return ordered per-URL normalized successes and
failures so partial provider responses remain visible. The tool adapter may
format those items together, but it must not report an overall clean success
when every requested URL failed.

### Future Content Import Boundary

Keep source type separate from user intent. A URL may be used by either of two
future-facing capabilities with different outcomes:

- `web_extract`: retrieve web content transiently for agent reasoning; no vault
  artifact or durable ingestion job is created.
- `content_import`: convert one or more sources into durable vault artifacts;
  URLs, vault PDFs, images, and other supported documents are all valid source
  types.

Do not make `content_import` file-only, and do not add persistence options to
`web_extract`. The future `content_import` tool should be a thin adapter over
the ingestion service. For URL sources, ingestion should call the shared web
transport/extraction primitives directly; it must never invoke the
model-facing `web_extract` tool.

Design normalized web fetch/extraction results so an ingestion adapter can
retain source URL, effective URL, MIME, title, fetched time, strategy, warnings,
and extracted Markdown without parsing model-formatted output. Keep provider
SDK response shapes and untrusted-data presentation wrappers outside that
normalized service contract.

The later ingestion branch can then add explicit source ownership and
destination policy without changing the web substrate:

- staging files under `AssistantMD/Import` may retain cleanup-after-success
  behavior;
- canonical vault files must be preserved by default;
- URLs have no source-file cleanup;
- destination and overwrite/collision behavior belong to ingestion, not web
  extraction.

### Strategy-Neutral Tool Contracts

Define capability arguments around common user intent, not current Tavily SDK
names:

- `web_search(query, max_results=...)`
- `web_extract(urls, include_images=false)`
- `web_crawl(url, instructions=..., max_depth=..., max_pages=...,
  allow_external=false)`

Clamp limits in the capability service before provider dispatch. A strategy
must either implement the declared contract or fail clearly during strategy
registration/configuration; it must not silently ignore unsupported options.
Provider tuning such as Tavily search depth belongs in strategy configuration
or implementation defaults until it represents a provider-neutral capability.

Tool adapters format normalized results for the model, apply the existing
untrusted-web-data boundary, and translate typed service failures into the
shared structured `ToolReturn` failure envelope. Direct Monty calls continue to
receive failures through the established tool-result-to-exception adapter.

### Strategy-Aware Availability

Provider-neutral tool declarations cannot express Tavily's secret requirement
through static `ToolConfig.requires_secrets`. Add strategy metadata that reports
required secrets and validates construction.

- `duckduckgo` search and `curl` extraction require no provider secret.
- Tavily search, extraction, and crawl require `TAVILY_API_KEY`.
- An unknown strategy or missing required secret is a configuration-health
  error tied to the capability and selected strategy.
- Chat/delegate binding should omit an unavailable capability with the existing
  explicit unavailable-tool note.
- An authored script that explicitly requests an unavailable capability should
  fail binding clearly rather than run with another strategy.

Keep `disabled_tools` as the advanced app-wide capability switch for this
release. Its default is an empty list; every registered tool remains available
unless explicitly denied. Strategy selection and capability availability remain
separate concerns.

### Failure Observability

Strategy failures must identify the operation that actually failed. Add one
activity-visible decision-boundary event:

`web_capability_failed`

Minimum payload:

- `event`, `status=failed`
- `capability`
- `strategy`
- `error_type`, `failure_kind`, `retryable`
- `http_status` when available
- a concise sanitized `error`
- request shape such as URL count or hostname, never search query text, page
  content, credentials, or complete request arguments

Return the same capability and strategy identifiers in structured tool failure
metadata. Keep successful per-call detail validation-only unless later usage
shows a user-facing diagnostic need; tool history already records successful
calls. Emit a compact validation event with capability, strategy, result count,
and duration so scenarios can prove routing without asserting model prose.

Use one shared URL-log sanitizer across web capabilities and URL ingestion.
Execution and the durable ingestion job may retain the complete source URL, but
activity and validation events must omit credentials, query strings, and
fragments. Replace ingestion's current complete `source_uri`/options logging
with the sanitized URL identity and explicit non-sensitive option names.

## Proposed Code Shape

Create a provider-independent `core/web/` subsystem with ownership similar to:

- `models.py`: normalized fetch/search/extract/crawl result models
- `errors.py`: typed configuration, transport, provider, and extraction errors
- `security.py`: shared URL scheme, DNS/IP, redirect, and public-network policy
- `fetchers/`: transport registry and the bounded curl implementation
- `extractors/`: reusable HTML-to-Markdown conversion
- `strategies/`: DuckDuckGo and Tavily search, curl and Tavily extract, Tavily
  crawl
- `registry.py`: capability-specific strategy registration and resolution
- `service.py`: argument validation, limit enforcement, strategy dispatch, and
  normalized observability metadata

Exact file boundaries may be combined where modules would otherwise be trivial,
but keep transport, content extraction, capability orchestration, and
model-facing formatting as distinct responsibilities.

Replace the four provider-named modules under `core/tools/` with thin
`web_search.py`, `web_extract.py`, and `web_crawl.py` adapters. Remove provider
SDK calls, secret lookup, and provider-specific formatting from tool modules.

Adapt `core/ingestion/sources/web.py` and the HTML extraction strategy to call
the shared web primitives while preserving ingestion's `RawDocument`,
`ExtractedDocument`, job, provenance, and artifact contracts.

## Browser Resource Policy

Treat browser hardening as part of this effort because the tool-surface gap
exposed the resource failure.

- Retain the shipped `2G` container limit as the standard browser-capable
  baseline until measurements of the serialized implementation justify a
  change. Do not use a higher default to mask uncontrolled concurrency.
- Document two operating profiles:
  - standard/browser-capable: at least 2 GB available to AssistantMD, browser
    enabled, and one active Chromium session;
  - lightweight: approximately 1 GB, browser disabled, with `web_extract` used
    for ordinary static-page retrieval.
- Treat browser support below the documented baseline as unsupported/degraded
  configuration. Surface a configuration-health warning when a detectable
  cgroup memory limit is below that baseline and browser is enabled.
- Add a process-wide browser semaphore, defaulting to one active Chromium
  session.
- Add explicit browser concurrency and per-turn call-limit settings rather than
  relying only on the generic chat tool-call limit.
- Read cgroup v2 memory usage, limit, and OOM event counters when available.
- Refuse a browser launch with a structured resource failure when configured
  headroom is unavailable.
- Include cgroup/container memory context in browser lifecycle diagnostics;
  retain portable process metrics when cgroups are unavailable.
- Document that a kernel/container OOM kill cannot reliably produce an
  in-process terminal activity or Logfire event, and document the Docker status
  checks needed to confirm `OOMKilled` and restart count.
- Explain in Docker/setup documentation that `limits.memory`,
  `reservations.memory`, and `shm_size` are separate controls and that a 2 GB
  container limit cannot compensate for a host with less available memory.
- Keep browser explicit. `web_extract` must report dynamic/thin content as its
  configured strategy's result or failure, not launch Chromium automatically.

## Settings and Migration

This changes persisted settings and authoring contracts.

1. Add the four string strategy settings to the settings template and expose
   them through the existing raw-string settings editor.
2. Replace provider-named entries in the tool registry with `web_search`,
   `web_extract`, and `web_crawl` entries.
3. Replace the app-wide allowlist with an empty `disabled_tools` denylist so new
   registered tools become available without settings maintenance.
4. Add a centralized settings upgrade transformation that rewrites legacy tool
   names and converts the old allowlist to a `disabled_tools` complement against
   current built-ins and user-editable custom tools. Do not put YAML settings changes into the
   versioned SQLite migration system. Extend the existing backed-up **Repair
   settings from template** path unless implementation proves that boot would
   be unsafe before a user can run it; if startup migration is required, create
   one centralized versioned settings migrator rather than adding an ad hoc
   one-time bootstrap check.
5. Infer a legacy search preference only when exactly one old search provider
   was enabled. When both or neither were enabled, use the documented template
   default rather than inventing an ordering-based preference.
6. Map legacy Tavily extract/crawl enablement to the corresponding capability;
   provider selection remains the explicit new strategy setting.
7. Rename `ingestion_url_fetch_backend` to
   `ingestion_url_fetch_strategy` through the same centralized settings upgrade
   transformation while preserving its current `curl` value.
8. Report unknown strategies, unavailable selected strategies, and missing
   strategy secrets through configuration health after reload.
9. Add the retired provider tool names to the existing retired-name guard and
   do not retain runtime aliases. Authoring scripts and prompts must move to the
   stable capability names.

Update system and vault authoring templates, virtual tool documentation,
examples, release notes, and upgrade guidance. The upgrade guidance should tell
users to run **Refresh Authoring Scripts**, review custom automations for old web
tool names, run **Repair settings from template**, and set Tavily strategies
explicitly where desired.

## Implementation Slices

### Slice 1: Shared Web Substrate

- Add normalized models, typed errors, registries, and strategy protocols.
- Extract the curl transport and HTML-to-Markdown implementation into shared
  web primitives.
- Apply shared public-network validation to the initial URL and every redirect;
  preserve bounded timeouts, response-size limits, and content-type handling.
- Add the shared URL-log sanitizer and remove complete URL/query data from URL
  ingestion lifecycle events.
- Adapt ingestion to the shared primitives without changing stored artifacts or
  job lifecycle behavior.
- Preserve `clean_html`, fetched/effective URL metadata, MIME/title handling,
  selected-strategy provenance, renderer frontmatter, output collision policy,
  and task-owned vault mutations at the ingestion adapters.
- Add focused tests for redirects, private targets, oversize responses,
  extraction provenance, and ingestion parity.

### Slice 2: Capability Tools and Strategies

- Implement DuckDuckGo/Tavily search, curl/Tavily extract, and Tavily crawl as
  registered strategies returning normalized results.
- Add the three thin model-facing capability tools and provider-neutral docs.
- Centralize result formatting, untrusted-data wrapping, limit enforcement, and
  structured failure conversion.
- Remove the provider-named tool implementations after all call sites move.

### Slice 3: Settings, Binding, and Contract Migration

- Add string strategy accessors and strategy-aware configuration health.
- Update tool binding so selected-strategy secret requirements are enforced for
  chat, delegate, workflows, context scripts, and code execution consistently.
- Extend and exercise the centralized settings repair/upgrade path; introduce a
  settings schema migrator only if the application cannot safely reach that
  repair path with legacy tool configuration.
- Update tool-availability settings, constants, caches, authoring templates, docs,
  and validation fixtures to stable capability names.
- Confirm settings reload refreshes strategy resolution and health caches.

### Slice 4: Browser Guardrails and Operational Diagnostics

- Add process-wide concurrency control and per-turn browser limits.
- Add cgroup-aware launch headroom checks and lifecycle metadata.
- Return structured resource failures and emit compact activity diagnostics.
- Update the Compose comments, container/setup guidance, browser tool
  documentation, and configuration health for the standard and lightweight
  profiles.

### Slice 5: Hardening and Architecture Alignment

- Review web, ingestion, settings, and tool-binding paths for duplicate provider
  policy or result formatting.
- Verify no automatic provider fallback remains.
- Update `docs/architecture/ingestion-pipeline.md`,
  `docs/architecture/llm-tools.md`, and
  `docs/architecture/settings-secrets.md` to the current contract.
- Add an ADR for stable web capabilities with explicit strategy selection and
  shared web substrate ownership.
- Remove retired provider docs/modules and stale instructions that recommend
  Tavily-to-browser fallback as infrastructure behavior.

## Validation Targets

Add or extend focused integration scenarios before implementation to prove:

- `web_search`, `web_extract`, and `web_crawl` dispatch only to their configured
  strategy;
- a configured strategy failure returns its real identity and structured
  classification without invoking another provider or browser;
- missing Tavily credentials make a Tavily-selected capability visibly
  unavailable in configuration health and tool binding;
- chat, delegate, and Monty direct calls resolve the same capability and
  strategy contracts;
- successful web output retains the untrusted-data boundary;
- URL ingestion and curl-backed `web_extract` use the same transport and HTML
  conversion behavior while preserving ingestion artifacts;
- URL ingestion preserves `clean_html`, durable job outcomes, selected strategy
  frontmatter, collision-safe output paths, and Vault Activity mutations, while
  `web_extract` performs no vault persistence;
- mixed-success multi-URL extraction preserves each URL's outcome and an
  all-failed call returns structured failure semantics;
- initial URLs and every redirect to local/private networks are rejected;
- URL ingestion and web-capability logs use sanitized URL identities while the
  durable ingestion job retains the executable source URL;
- the settings upgrade path rewrites old tool names and the ingestion fetch key
  without discarding unrelated settings or custom tools;
- strategy changes take effect after configuration reload;
- concurrent browser calls respect the semaphore, and low-memory launch refusal
  returns a structured resource failure;
- a detectable sub-baseline cgroup limit with browser enabled produces a clear
  degraded configuration-health result;
- `web_capability_failed` contains capability and strategy but excludes query
  text, page content, and secrets.

Run fast helper smoke tests and the individual affected scenarios locally.
Maintainers should run the broader validation suite according to the repository
validation workflow.

## Contract-Sensitive Areas

- persisted `system/settings.yaml` and centralized settings repair/upgrade
- settings/configuration-health API and cache reload
- app-wide disabled tool names and derived availability
- chat, delegate, workflow, context-script, and Monty direct-tool binding
- tool names and argument schemas stored in chat history or authoring scripts
- untrusted web-result wrapping and oversized tool-output caching
- ingestion URL provenance and stored artifacts
- URL import API `clean_html` behavior and durable ingestion job status
- activity-log failure events and sanitization
- Docker/browser resource behavior

## Non-Goals

- Automatic strategy or provider fallback
- Making Tavily a required installation dependency or credential
- Building a general-purpose internal crawler in this iteration
- Automatically escalating extraction to Chromium
- Building the future agent import tool itself
- Adding vault-explorer import actions or redesigning ingestion source and
  destination policy in this branch
- Persisting fetched web content outside existing tool cache or ingestion
  artifact contracts
- Replacing the ingestion job, renderer, storage, or vault-mutation systems

## Outcome

All five implementation slices are complete. The resulting contract is recorded
in ADR 0027 and the web, ingestion, settings, tool, browser, setup, and release
documentation referenced above.
