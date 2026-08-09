# URL Library Automation Plan

## Goal

Enable chat agents and workflows to build a vault-native research/source library from:

- explicit URL lists
- search/crawl-derived URL lists
- bounded discovery from a seed page

while reusing the existing ingestion pipeline for deterministic import and artifact writing.

Update after Monty authoring: this should no longer be treated as a standalone
research automation subsystem. The durable backend should provide deterministic
import primitives and status contracts. Search strategy, URL selection, library
index generation, retry policy, and summarization should mostly live in Monty
workflow templates and context/tool usage.

## Supported Scenarios

The design should support these entry modes with the same backend import engine:

- a user gives the agent an explicit mixed list of URLs
- a user gives the agent a research direction and the agent builds a URL list through search/crawl before importing
- a user gives the agent a seed page or blog index and the agent discovers bounded child links before importing
- a user pastes one URL or many URLs into the UI and gets the same import behavior without involving an agent

## Desired Outcomes

For all of the above, the system should be able to:

- ingest mixed source types in one run
- produce stable markdown-first vault artifacts
- clearly mark inaccessible or blocked sources for manual follow-up
- avoid duplicate output on reruns unless explicitly forced
- preserve enough structured status that workflows or UI can resume, poll, summarize, or retry

## Scope

This plan covers the highest-value upgrades needed to make ingestion usable as a general source-library builder:

1. mixed-source routing for URLs and API-like endpoints
2. batch import support on top of the existing ingestion system
3. agent/workflow access through a Monty-friendly import primitive
4. optional bounded browser fallback after the HTTP path is solid
5. slim Docling-backed extraction strategies for HTML, Office files, and
   lightweight PDF handling

## Architectural Direction

### 1. Keep ingestion focused on deterministic import

`core/ingestion` should remain the execution engine that:

- classifies/fetches a source
- chooses the extraction strategy
- writes stable vault artifacts
- records durable job status and outputs

It should not become the place where search strategy, topical discovery, or LLM planning lives.

### 2. Move orchestration into Monty-friendly primitives

The Monty authoring environment now makes it unnecessary to push all automation into dedicated backend endpoints.

Agent/workflow logic can already do:

- search for candidate URLs
- crawl or discover child links
- filter, dedupe, and score candidates in Python
- build markdown index files
- poll queue state and decide what to do next

What is missing is a durable import primitive that Monty can call without going through the manual UI.

### 3. Add one import-focused capability, not a research subsystem

The cleanest new primitive is a real implementation of `import_content(...)` or a closely related dedicated tool/helper.

Recommended shape:

`import_content(*, sources: list[str] | str, mode: str = "enqueue", options: dict | None = None)`

Core behavior:

- accept one or many sources
- classify each source into import action
- enqueue ingestion jobs and return structured per-source results
- optionally support bounded waiting/polling

This should expose deterministic import behavior to:

- chat
- workflows
- context templates
- future non-LLM UI/API flows

Research-library behavior should be shipped as authoring templates or examples
on top of this primitive, not hard-coded into ingestion. Examples include:

- search topic, import selected results, write `index.md`
- crawl seed page, import bounded children, write `manual_intervention.md`
- import URLs from a markdown file and summarize completed outputs
- retry failed or manual sources with a different policy

### 4. Reuse existing seams before inventing new ones

The current codebase already contains a few partial or latent extension points that should be treated as inputs to the design rather than ignored:

- the Monty helper stub `import_content(...)`
- ingestion model fields for `RenderMode.CHUNKED`, `Chunk`, `ExtractedDocument.blocks`, and chunk-related render options
- the existing renderer/storage split in `core/ingestion`

These do not mean the full feature already exists. They do mean the implementation should first ask whether these seams should be:

- completed and used as intended
- narrowed and simplified
- or explicitly removed/refactored if they are the wrong abstraction

The plan should avoid creating a second parallel abstraction when an existing seam is close to the desired boundary.

## Responsibility Split

### Deterministic backend responsibilities

- Mixed-source classification: `html`, `markdown`, `pdf`, `docx`, `xlsx`,
  `pptx`, `json`, `blocked`, `unknown`
- Source normalization and dedupe
- Enqueueing and status persistence
- Converting source-specific extraction results into a canonical markdown-oriented library artifact
- Stable output path generation
- Manual/failure reason classification
- Polling/status lookup for batched imports
- Runtime policy normalization and effective-strategy reporting
- Security boundaries for URL fetches and browser fallback
- Optional conversion of extracted browser/inline content through the same
  renderer/storage path

### Monty/workflow responsibilities

- Build candidate URL lists from search/crawl results
- Select and filter URLs for inclusion
- Chunk long research runs into batches
- Generate `index.md`, `manual_intervention.md`, and summary notes
- Retry or escalate based on returned statuses
- Decide whether a failed source is worth browser fallback
- Generate research-library presentation and source annotations
- Summarize imported artifacts after deterministic import is complete

## Routing Model

### Source classification

The backend import path should classify each source before dispatch.

Initial classification outcomes:

- `html`
- `markdown`
- `pdf`
- `docx`
- `xlsx`
- `pptx`
- `json`
- `blocked`
- `unknown`

### Detection heuristics

Classification should use lightweight ordered heuristics:

1. source URI hints such as suffix, scheme, or known document patterns
2. response `content-type`
3. response status and block signals such as `401`, `403`, `429`, challenge pages, or login walls
4. body signatures such as `%PDF`, HTML structure, or JSON shape

### Planned actions

Classification should map into a deterministic planned action:

- `import_html`
- `import_markdown`
- `import_pdf`
- `import_docx`
- `import_xlsx`
- `import_pptx`
- `import_json`
- `manual`
- `skip`
- `retry_or_fallback`

## Execution Surfaces

The same backend import path should be reachable from all of these surfaces:

- UI import flow
- API/service layer
- chat tool usage
- Monty workflows and context templates

The UI should be able to evolve from a single URL field to a multiline URL input without creating a second import system.

The chat tool and Monty helper should share the same service implementation and
return shape. Chat should not call a different import path from authored
workflows.

## Batch Execution Model

### Input shape

The import primitive should accept one or many sources.

Recommended logical shape:

`import_content(*, sources: list[str] | str, mode: str = "classify_and_import", options: dict | None = None)`

### Modes

The useful first-class modes are:

- `classify_and_import`
- `classify_only`
- `status`

Optional later addition:

- bounded `wait`/poll behavior for callers that want fast synchronous feedback without blocking indefinitely

### Runtime policy overrides

Strategy selection should allow a per-run override policy in a flat option shape.

Recommended v1 shape:

```python
import_content(
    sources=urls,
    mode="classify_and_import",
    options={
        "pdf_mode": "prefer_ocr",
        "html_mode": "http_only",
        "json_mode": "markdown",
    },
)
```

This supports the main interaction patterns:

- in chat, the user can inspect sources and ask the agent to prefer OCR for a specific run
- in workflows, the template can hardcode a run policy
- if no run policy is provided, ingestion falls back to settings defaults

### Policy precedence

Strategy policy should resolve in this order:

1. per-run policy from the current tool/helper call
2. configured defaults from settings
3. deterministic internal fallback rules within the selected mode

### PDF mode vocabulary

Useful v1 PDF policy values:

- `auto`
- `prefer_text`
- `prefer_ocr`
- `text_only`
- `ocr_only`
- `page_images`

These should express both preference and fallback intent.

Examples:

- `prefer_ocr`: OCR first, then text fallback if OCR is unavailable or fails
- `ocr_only`: do not fall back to text
- `auto`: use the default deterministic quality/routing heuristic
- `page_images`: bypass markdown conversion and render page images intentionally

### Effective strategy reporting

When runtime policy overrides are allowed, import results should record both:

- the effective requested policy
- the actual extraction strategy used

This keeps batch automation understandable and debuggable.

### Per-source status contract

Per source, the useful return contract is roughly:

- `source`
- `normalized_source`
- `classification`
- `planned_action`
- `status`
- `job_id`
- `reason`
- `attempt_count`
- `output_paths`
- `title`
- `last_error`
- `requested_policy`
- `effective_strategy`
- `manual_reason`
- `retryable`

Initial status vocabulary should remain close to existing ingestion semantics:

- `classified`
- `queued`
- `processing`
- `completed`
- `failed`
- `manual`

`status` mode should accept job IDs or sources and return this same per-source
shape so Monty workflows can poll without inspecting database internals.

## Content Processing Model

### Canonical output

The library should remain markdown-first even when inputs are mixed.

That means:

- HTML sources should end as markdown artifacts
- DOCX, XLSX, and PPTX sources should end as markdown artifacts
- PDF sources should end as markdown artifacts
- JSON/API sources should also end as markdown artifacts by default, even if a raw JSON sidecar is optionally preserved

The goal is to avoid building a vault library full of mixed raw payload types as the primary user-facing result.

### Docling-backed extraction strategy

Docling is now viable as a selective ingestion dependency because
`docling-slim` allows installing only targeted format support instead of the
old full model-heavy package.

Recommended initial dependency set:

```text
docling-slim[convert-core,format-web,format-office,format-pdf-pypdfium2,format-latex]
```

Measured in a clean Python 3.13 Linux virtualenv, this installed at roughly
406 MB. The size is mostly from NumPy, SciPy, Pillow, and native library wheels,
not from Docling itself. This is materially smaller than installing the full
Docling model stack.

Important package boundary:

- avoid depending on `docling` or `docling-slim[standard]` for this feature
- avoid Docling local OCR/model extras in the initial implementation
- use direct Docling backends where possible instead of the public
  `DocumentConverter` API, because the current converter import path pulls
  toward broad pipeline/model dependencies

Initial strategy mapping:

- `html_docling`: use Docling's HTML backend for local HTML and fetched URL
  HTML, then render markdown
- `markdown_docling`: use Docling's Markdown backend when normalization through
  Docling is useful; plain markdown pass-through remains acceptable
- `docx_docling`: use Docling's Word backend for DOCX
- `xlsx_docling`: use Docling's Excel backend for XLSX
- `pptx_docling`: use Docling's PowerPoint backend for PPTX
- `pdf_text_pdfium`: replace the current PyMuPDF selectable-text path with
  `pypdfium2`
- `pdf_page_images_pdfium`: replace the current PyMuPDF page-image renderer
  with `pypdfium2`
- `pdf_ocr_mistral`: keep Mistral OCR as the high-quality PDF extraction path
- `json_markdown`: implement as a small native deterministic JSON-to-markdown
  renderer, not as a Docling concern

This stack should support both local files and URLs that resolve to one of the
same file types. URL ingestion should therefore classify the fetched response by
final URL, content type, filename hints, and payload signatures, then dispatch
to the same extractor registry used for local files.

Docling's document model may become useful later for read-time structure,
chunking, or memory work. For this plan, do not make persisted
`DoclingDocument` artifacts part of the default ingestion contract. The v1
contract remains markdown-first output plus metadata and optional sidecar
artifacts.

### Suggested internal stages

To keep the design flexible, the ingestion path should be thought of as distinct stages:

1. source load/classification
2. source-specific extraction
3. optional content processing
4. markdown rendering
5. artifact storage

Today, stages 2 and 4 are the important ones. The design should leave a clean seam for stage 3.

### Future processing seam

The optional processing stage should sit between extraction and final rendering.

That stage can later support features such as:

- chunking or sectioning strategies
- normalization and cleanup
- heading repair or document restructuring
- JSON-to-markdown shaping
- on-demand structured document construction for readers or workflows that need
  richer structure
- metadata enrichment

v1 does not need to implement these as a broad framework. It just should not hard-code the pipeline into a single extract-and-dump step that makes later insertion awkward.

### Practical implication for v1

The simplest way to preserve flexibility is:

- keep extraction responsible for producing structured extracted content
- keep rendering responsible for producing final markdown artifacts
- reserve a narrow processing seam between them, even if v1 mostly passes extracted content through unchanged

This keeps future chunking or transformation work additive instead of forcing a later pipeline rewrite.

### Browser and inline content handoff

Browser fallback should not become a second writing path. If a Monty workflow
uses `browser`, `tavily_extract`, or another tool to recover content from a URL,
there should eventually be a host-owned way to pass that extracted content back
through ingestion rendering/storage.

Possible later helper shape:

```python
import_content(
    sources=[{
        "source": "https://example.com/blocked",
        "content": extracted_markdown,
        "mime": "text/markdown",
        "title": "Recovered page title",
    }],
    mode="classify_and_import",
    options={"source_mode": "inline"}
)
```

This preserves one artifact layout, one frontmatter convention, and one status
contract even when recovery happens outside the normal HTTP fetch path.

## UI And API Direction

This plan intentionally extends the existing ingestion system rather than replacing it.

That means:

- the UI can paste one URL or many URLs and call the same service path
- the API can expose batch classification/import behavior without inventing a separate agent-only backend
- workflows and chat can call the same import path through a tool/helper

If a batch-specific API is added, it should be a thin wrapper over the same ingestion service behavior rather than a parallel pipeline.

## Recommended Phases

### Phase 1: Import primitive and status contract

- Implement `import_content(...)` for Monty and/or add an equivalent chat tool
- Back both surfaces with the same service implementation
- Add mixed-source router for URL/file/http endpoint classification
- Add Docling/pypdfium2-backed extractor strategies for `html`, `markdown`,
  `docx`, `xlsx`, `pptx`, PDF selectable text, and PDF page images
- Keep Mistral OCR as the preferred high-quality OCR strategy for PDFs
- Support `html`, `markdown`, `pdf`, `docx`, `xlsx`, `pptx`, `json`, `blocked`,
  `unknown`
- Return structured per-source outcomes with job ids and reasons
- Support flat per-run policy overrides such as `pdf_mode`, `html_mode`, and `json_mode`
- Add `status` mode for job IDs and sources
- Normalize policy vocabulary and record requested policy plus actual strategy
- Keep implementation centered on `core/ingestion` so UI, API, and agent callers share the same backend behavior

### Phase 2: Structured research tool outputs

- Update or wrap search/crawl/extract tools so Monty can access structured URL
  candidates without brittle string parsing
- Preserve human-readable tool returns, but expose URLs, titles, snippets,
  failed URLs, and extraction metadata through tool metadata or cache refs
- Validation target: a Monty workflow can search, dedupe URLs, call
  `import_content`, and write a simple index without regex-parsing prose

### Phase 3: Library workflow templates

- Add reusable workflow patterns for writing library metadata alongside the existing import output root
- Reuse `ingestion_output_path_pattern` and the current per-import subfolder layout for imported source artifacts
- Keep any aggregate index/manual files in that same configured import root unless the user explicitly chooses another location
- Ship examples rather than a hard-coded research library subsystem:
  - explicit URL list import
  - search-result import
  - seed-page child-link import
  - failed/manual follow-up report

### Phase 4: Browser fallback

- Add opt-in browser fallback only after HTTP-based routing is solid
- Keep it bounded and deterministic
- Route unresolved pages to manual intervention instead of repeated expensive retries
- Limit browser fallback to cases that are plausibly recoverable from a browser session, rather than using it as a universal second pass
- Prefer a browser/inline-content handoff into ingestion rendering/storage over
  ad hoc workflow writes

### Phase 5: Discovery workflows

- Build example workflows that:
  - search by topic, then import results
  - crawl a seed page, then import discovered links
  - process explicit user-supplied URL files

### Final stage: User documentation and operational tuning

- Document that submitted imports enter the durable queue and are picked up by
  the scheduled ingestion worker rather than processed inline.
- Explain how `ingestion_worker_interval_seconds` controls pickup latency and
  how `ingestion_worker_batch_size` controls the number of jobs selected and
  processed concurrently per worker run.
- Include practical tuning guidance for interactive agent imports versus
  lower-frequency background ingestion, including the resource and external API
  pressure created by shorter intervals or larger batches.
- Clarify that batches larger than `ingestion_worker_batch_size` require
  multiple worker runs and that slow jobs can extend the effective wait because
  scheduled worker runs do not overlap.
- Keep immediate event-driven queue draining out of scope unless operational
  experience shows that configurable polling cannot provide acceptable
  responsiveness.

### Final stage: Import queue observability and controls

Implementation status: complete; pending maintainer full-suite validation and
manual Dashboard visual review.

Scope:

- Add a recent import-status panel at the top of the Dashboard Import section,
  backed by the durable ingestion job store rather than process-local execution
  task history.
- Show job id, source, vault, status, timestamps, outputs, and errors for recent
  jobs across vaults.
- Poll while queued or processing jobs exist and provide an explicit refresh
  action at all times.
- Allow cancellation only while a job remains queued. Processing jobs are not
  presented as cancellable because their thread and external extraction calls
  cannot currently be stopped reliably.
- Add a section-level `Process queue now` action that advances the existing
  scheduler-owned ingestion worker instead of creating a parallel drain path;
  configured batch size and non-overlap policy remain authoritative.

Affected areas:

- `core/ingestion/jobs.py` and `api/services/ingestion.py`: durable listing,
  queued-only cancellation, and scheduler trigger service contracts.
- `api/import_models.py` and `api/endpoints.py`: recent-job list, cancel, and
  process-now API contracts.
- `static/index.html` and `static/js/configuration.js`: Import panel rendering,
  controls, status polling, and action feedback.
- `docs/architecture/ingestion-pipeline.md`: current queue visibility and
  control contract.

Validation target:

- Extend the ingestion integration scenario to prove recent listing order and
  projection, queued-only cancellation, worker exclusion of cancelled jobs, and
  scheduler-backed process-now behavior.
- Add stable validation events at successful queued cancellation and manual
  scheduler trigger boundaries with job id/count and trigger source.
- Use targeted frontend syntax/build checks for the Dashboard wiring; visual
  layout remains a manual review target.

Next implementation steps:

1. Add the durable status/cancellation store operations and API models.
2. Add service endpoints and scheduler trigger behavior.
3. Add validation assertions before wiring the Dashboard panel.
4. Implement UI rendering, actions, and conditional polling.
5. Update current-contract documentation and run static quality gates.

## Design Notes

### Existing seams to evaluate

Before adding new primitives, implementation should explicitly review and decide the fate of the current partial hooks:

- `core/authoring/helpers/import_content.py` (currently registered but not implemented)
- `core/ingestion/models.py` fields related to chunked rendering and extracted blocks
- `core/ingestion/pipeline.py` as a possible place for a processing stage

Expected decision for each seam:

- use as-is
- use with expansion
- refactor/rename
- deprecate

That decision should be intentional and documented in the implementation work, so the system does not accumulate duplicate concepts for import orchestration or content processing.

### JSON/API endpoints

This should be first-class in routing rather than an afterthought.

For JSON responses:

- render a markdown view as the default library artifact
- optionally preserve raw JSON as a sidecar artifact when useful
- keep the import result typed as `json`/`api_json` internally rather than forcing HTML semantics

### URL downloads and document files

URL ingestion should not assume that every successful HTTP response is HTML.
Fetched URLs may resolve to downloadable documents such as PDFs, DOCX files,
XLSX workbooks, PPTX decks, markdown files, or JSON endpoints.

The importer should preserve:

- requested URL
- final URL after redirects
- response content type
- filename hints from URL and `Content-Disposition`
- detected source type
- source hash

The extractor registry should then receive a `RawDocument` that is equivalent
to the local-file path for the same bytes. This keeps local files and URL
downloads on one strategy path.

### Conversion policy

The difficult part of automation is not orchestration but source-to-markdown conversion quality.

That logic should remain deterministic and policy-driven inside ingestion, not delegated to ad hoc LLM judgment per source.

The agent or workflow may choose a run policy, but ingestion should own:

- source classification
- strategy selection within the allowed policy
- fallback behavior
- metadata about what actually ran

Docling strategy selection should be deterministic. If a Docling backend is
unavailable, misconfigured, or unsupported for a source, the job should fail or
fall back according to the configured policy rather than asking an LLM to infer
conversion behavior.

### Durable status shape

Retry policy should distinguish between:

- transient failures such as transport timeouts, `5xx`, and some `429` responses
- hard-access failures such as `401`, `403`, paywall/login requirements, or anti-bot blocks

Transient failures may be retried with bounded backoff. Hard-access failures should usually move directly to `manual`.

### Library generation

I would not make ingestion itself own a separate `ResearchLibrary/` tree.

That is a presentation/orchestration concern and fits better in:

- a reusable workflow
- a Monty helper layered on top of import results
- or a thin service wrapper if the UI needs a non-LLM path

Imported source artifacts should keep using the existing configured ingestion root from `ingestion_output_path_pattern` and the current per-import subfolder naming logic. If we add aggregate files such as `index.md` or `manual_intervention.md`, they should default to that same configured root rather than introducing a second library base path.

With Monty authoring in place, the default product shape should be:

- host-owned import primitive
- seed authoring templates for common research-library patterns
- optional UI batch import that calls the same primitive
- no dedicated backend research pipeline unless repeated non-LLM UI needs force
  a thin service wrapper

## Non-Goals

These do not belong in the first implementation pass:

- paywall bypass or credential automation
- broad autonomous report writing as part of the import engine
- browser-first extraction for all URLs
- tightly coupling topical search/crawl discovery into `core/ingestion`
- a separate research automation scheduler, database, or pipeline parallel to
  ingestion jobs and Monty workflows
- ad hoc workflow writes for imported source artifacts that bypass ingestion
  rendering/storage

## Open Questions

- Whether `import_content(...)` should be a Monty helper only, a chat tool only, or both backed by the same service
- Whether batch imports need a first-class batch table, or whether per-job tracking plus returned job ids is enough initially
- Whether browser fallback belongs inside ingestion routing or as a second explicit retry mode
- How much built-in markdown index generation should be productized versus shipped as example workflows
- Whether structured URL candidate metadata should be added to existing tools or
  exposed through a new discovery helper
- How force/rerun semantics should work with the current duplicate-safe output
  suffixing behavior
- Whether persisted structured-document caches are worth adding later, after
  read-time use cases prove the need

## Tool Boundary Hardening

Observed manual testing exposed two adjacent failure modes at the boundary
between transient web extraction and durable content import:

- `web_extract` can receive a PDF or other binary response and accidentally
  return decoded bytes as an enormous tool result.
- otherwise valid tool metadata can contain YAML-derived temporal values that
  SQLite event persistence cannot serialize with plain `json.dumps`.

The implementation should:

1. reject non-text responses in the curl extraction strategy before decoding,
   preserving per-URL partial-result behavior and directing callers to
   `content_import` for durable document ingestion;
2. make the one-line `web_extract` tool description and user-facing tool docs
   distinguish readable web pages from PDFs and other downloadable files;
3. normalize chat tool-event arguments and result metadata to JSON-compatible
   values at the persistence boundary so diagnostic recording cannot abort a
   chat stream;
4. add regression assertions to `web_capability_strategies` for binary rejection
   and to `chat_tool_replay_contract` for temporal metadata persistence.

No new validation event is required: binary rejection is already represented
by the existing typed per-item web failure contract, and successful tool-event
persistence is directly observable through the session detail contract.

## Import Job List Usability

The Import status panel should present operational work by default without
making durable job history inaccessible.

### Recommended contract

- Add server-side multi-status filtering to `GET /api/import/jobs`.
- Default the UI to `queued`, `processing`, and `failed`; completed and
  cancelled jobs remain available through status filters.
- Return a bounded page (recommended default: 25) and an opaque cursor for
  loading older matching jobs. Filtering must happen before the page limit.
- Keep accumulated pages inside a vertically bounded, scrollable table region;
  loading older history must not continuously expand the Import section.
- Show status totals for the active filter so the summary does not imply that
  the visible page is the complete job history.
- Preserve automatic polling whenever the selected result set includes queued
  or processing work, along with the existing cancel and run-now actions.
- Silent polling must not rebuild an unchanged table, and genuine updates must
  preserve the table's vertical scroll position.
- The table must remain horizontally constrained: desktop cells wrap long
  sources and errors, while narrow screens use the existing stacked-row pattern
  rather than exposing a horizontal scrollbar.
- URL jobs expose a reuse action that loads the original vault and URL into the
  manual import controls. The user can adjust the available settings before
  explicitly submitting a new job; prior job history is preserved.
- The vault selector sits at the top of the Import section and scopes both the
  visible job history and all inbox/URL submissions below it. An empty vault
  selection must never fall back to showing cross-vault history.
- URL response-limit failures report the configured threshold in MB, matching
  the unit used by `ingestion_url_max_response_mb`.

This combines status filters with pagination. Showing only queued jobs would
hide processing state and actionable failures, while date rotation alone would
still mix completed noise into the operational view.

### Affected areas

- `core/ingestion/jobs.py`: filtered, cursor-bounded query and matching counts
- `api/services/ingestion.py`, `api/endpoints.py`, and `api/import_models.py`:
  public query and response contracts
- `static/index.html` and `static/js/configuration.js`: status controls, summary,
  filtered loading, and Load Older behavior
- import API/UI validation scenario: assert filtering occurs before limiting,
  paging has no duplicate jobs, and default UI contract includes queued,
  processing, and failed statuses

No database migration or retention policy change is needed. Durable jobs remain
in the subsystem-owned ingestion database; this work only changes how history
is queried and presented. The next phase is Feature Development, beginning with
the API scenario and persistence query contract.
