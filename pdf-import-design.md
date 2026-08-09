# PDF Import Design Review

## Objective

Modernize PDF import as a quality-aware, provider-extensible document conversion
system while preserving the existing importer/extractor split and keeping heavy
OCR runtimes outside the AssistantMD process.

This is a design plan. It does not authorize implementation or change the
current ingestion contract.

## Current State

PDFs from vault files and URLs converge on the same `RawDocument` path. Markdown
mode runs an ordered list of strategies; the first strategy returning any
non-empty text wins. The default order is `pdf_text`, then `pdf_ocr`. A separate
`page_images` mode bypasses text extraction.

Current strategies:

- `pdf_text`: PyMuPDF plain-text extraction
- `pdf_ocr`: Mistral `/v1/ocr`, sending the complete PDF as a base64 data URL
- `page_images`: deterministic local rendering with a Markdown image index

The selected strategy is written to output frontmatter and activity events, but
is not persisted on the ingestion job or shown in the Import table.

## Critical Findings

### Strategy selection is success-aware, not quality-aware

`pdf_text` wins if it returns any non-whitespace text. This incorrectly accepts:

- scanned PDFs with a sparse or broken hidden text layer
- mixed PDFs where only some pages contain native text
- multi-column or table-heavy PDFs whose extracted reading order is unusable
- documents with headers/page numbers but no meaningful body extraction

An ordered fallback list cannot solve this by itself. Extraction results need an
acceptance/quality contract, and PDF routing needs document evidence before it
decides whether local text is sufficient.

### The Mistral adapter is behind the current API

The adapter currently retains page Markdown and optional image base64 payloads.
It discards or does not request:

- OCR 4 structural blocks, labels, reading order, and bounding boxes
- page- or word-level confidence scores
- explicit table output (`markdown` or `html`)
- separated headers and footers
- hyperlinks, page dimensions, response model identity, and usage information
- document and bounding-box annotations
- selective page ranges

The request uses a hard-coded 60-second timeout and always embeds the complete
document in JSON, adding base64 overhead. It does not use Mistral file upload or
direct document URLs, file upload, or batch OCR for large workloads.

There is also a current option translation defect: direct manual URL imports
place `capture_ocr_images` inside `extractor_options`, while the Mistral strategy
expects the internal key `ocr_capture_images`. The shared `ContentImportService`
does translate this correctly; the direct API path does not.

### “OCR provider” and “PDF policy” are conflated

The UI exposes PDF mode and an OCR checkbox, while settings expose a raw ordered
strategy list. These represent different decisions:

- desired artifact: Markdown or page-image index
- routing policy: automatic, local-only, OCR-first, or forced provider
- OCR provider/model: Mistral, Azure, Adobe, self-hosted service, etc.
- enrichment: images, tables, blocks, confidence, annotations

These should be modeled separately so adding providers does not multiply modes
or create provider-specific UI branches.

## Current Mistral Capabilities Worth Using

As of August 2026, `mistral-ocr-latest` resolves to OCR 4. The current API can:

- produce page Markdown with preserved structure, tables, images, and links
- emit paragraph-level blocks with structural labels and bounding boxes
- provide page or word confidence scores
- separate headers and footers from main Markdown
- return tables separately as Markdown or HTML
- process selected pages and page ranges
- produce schema-constrained document or bounding-box annotations
- accept uploaded OCR files up to 512 MB
- run OCR through asynchronous batch processing for high-volume workloads

OCR 4 is priced above OCR 3, so model aliases and resolved model identity must be
observable. Keep `mistral-ocr-latest` as the recommended editable default, but
persist the response's actual model so a moving alias never obscures provenance.

Primary references:

- [Mistral OCR API](https://docs.mistral.ai/api/endpoint/ocr)
- [Mistral OCR processor](https://docs.mistral.ai/studio-api/document-processing/basic_ocr)
- [Mistral OCR 4 model card](https://docs.mistral.ai/models/model-cards/ocr-4-0)
- [Mistral document annotations](https://docs.mistral.ai/studio-api/document-processing/annotations)
- [Mistral platform limits](https://docs.mistral.ai/resources/known-limitations)
- [Mistral changelog](https://docs.mistral.ai/resources/changelogs)

## Provider Landscape

| Provider | Fit for vault Markdown | Strengths | Integration cost | Recommendation |
| --- | --- | --- | --- | --- |
| Mistral OCR 4 | Excellent | Native Markdown, images, tables, links, blocks, confidence, annotations, batch | Low; current adapter exists | First-class default |
| Azure Document Intelligence Layout | Excellent | Markdown output, headings/sections, tables, figures, broad formats, up to 2,000 PDF pages on paid tier | Medium; async API and Azure credentials | First alternative |
| Adobe PDF Services | Excellent for PDFs | Direct PDF-to-Markdown plus structured JSON, tables, figures, native and scanned PDFs | Medium; asset upload, job polling, two-part credentials | Strong PDF-specific alternative |
| Google Document AI | Good after normalization | Mature OCR, quality analysis, 200+ languages, large batch support | High; processor/project setup and structured response conversion | Add for GCP demand |
| AWS Textract | Fair after normalization | Layout, tables, forms, confidence, mature async PDF processing | High; block graph to Markdown and S3-oriented async flow | Lower priority |
| Gemini document understanding | Prompt-dependent | Whole-document visual reasoning, structured output, up to 1,000 pages/50 MB | Medium; transcription is generative rather than a stable OCR contract | Optional experimental strategy |
| PaddleOCR PP-StructureV3 service | Good | Self-hosted Markdown, layout, tables, formulas, charts, reading order | Medium/high operational burden | Generic external-service target |
| olmOCR service | Good | Markdown-focused, tables/equations/reading order, OpenAI-compatible remote inference | Medium/high GPU or provider burden | Generic external-service target |

Primary alternative-provider references:

- [Azure Document Intelligence Layout](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/prebuilt/layout?view=doc-intel-4.0.0)
- [Adobe PDF Extract](https://developer.adobe.com/document-services/docs/overview/legacy-documentation/pdf-extract-api/)
- [Adobe PDF Services workflow](https://developer.adobe.com/document-services/docs/overview/pdf-extract-api/gettingstarted)
- [Google Enterprise Document OCR](https://docs.cloud.google.com/document-ai/docs/processors-list)
- [AWS Textract document analysis](https://docs.aws.amazon.com/textract/latest/dg/how-it-works-analyzing.html)
- [Gemini document understanding](https://ai.google.dev/gemini-api/docs/document-processing)
- [PaddleOCR PP-StructureV3](https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/PP-StructureV3.html)
- [AllenAI olmOCR](https://github.com/allenai/olmocr)

## Recommended Architecture

### Pydantic AI reuse boundary

Current Pydantic AI provides provider-neutral multimodal document inputs through
`DocumentUrl`, `BinaryContent`, and `UploadedFile`. It also owns useful URL
transport behavior for model prompts: a provider may receive the URL directly,
or Pydantic AI can download an HTTP(S) URL with SSRF protection when
`force_download` is enabled.

That surface does not wrap dedicated document-processing or OCR APIs. In
particular, `MistralModel` maps PDF `DocumentUrl` and `BinaryContent` values into
Mistral chat-completion message chunks; it does not call `/v1/ocr`, model OCR
blocks/tables/confidence/annotations/page ranges, or normalize OCR responses.
Mistral `UploadedFile` is also unsupported in the current model adapter.

Stage 2 should therefore:

- reuse Pydantic AI's terminology and input-shape concepts where they improve
  consistency, especially URL versus bytes versus provider file references;
- evaluate its shared protected-download helper before adding another generic
  downloader, while retaining AssistantMD's existing ingestion transport and
  policy unless reuse is a clean architectural fit;
- continue using a dedicated OCR adapter for the Mistral OCR endpoint and its
  provider-specific request/response fields;
- define only the small normalized OCR result and capability contract needed by
  ingestion, rather than recreating Pydantic AI's general model/provider layer;
- periodically re-check Pydantic AI before adding provider adapters, because an
  OCR capability could be added in a future release.

### Keep extraction strategies format-aware

Strategy identifiers and routing remain aware of the source format even when
implementations share provider machinery. For example, future strategies may
include `word_ocr`, `word_docling`, `presentation_ocr`, or
`presentation_docling`, while `pdf_ocr` and `pdf_text` remain PDF-specific.

The shared layer should be limited to reusable mechanics such as Mistral request
transport, option translation, response parsing, and normalized provider
errors. Each format strategy continues to own:

- the MIME types and extensions it accepts;
- format-specific preflight and validation;
- applicable extraction options and provider capability checks;
- acceptance criteria and fallback order;
- conversion of the shared provider result into that format's ingestion result.

This permits competing implementations such as Mistral OCR, Docling, or native
Office parsing to be evaluated per format without creating one global document
strategy or assuming that a provider supports every format through every
transport. Add strategy names only alongside implemented and validated formats;
do not introduce speculative registrations.

### 1. Introduce an explicit PDF routing policy

Replace raw strategy ordering as the main user concept with:

- `auto`: inspect native extraction quality, then accept local text or use the
  configured OCR provider
- `local_text`: never send the document to a remote OCR provider
- `ocr`: use the selected OCR provider directly
- `page_images`: produce the deterministic page-image index

Keep ordered strategies internally for compatibility and fallback, but resolve
them from the policy plus provider configuration.

### 2. Add a quality profile and acceptance decision

Local PDF inspection should produce evidence such as:

- page count and encrypted/password status
- characters and words per page
- pages with meaningful native text
- printable/replacement-character ratios
- image-dominant and text-sparse page counts
- basic reading-order/layout risk signals

An extraction result should carry a normalized quality summary. `auto` accepts
`pdf_text` only when the local result passes configured policy; “non-empty” is
not sufficient. Exact thresholds should be derived from a representative corpus
rather than guessed in production code.

Mixed PDFs should initially route to whole-document OCR when local quality is
inconsistent. Selective page OCR and deterministic page merging can follow once
the normalized page model is proven.

### 3. Normalize provider results

Define a provider-neutral OCR result containing:

- document Markdown
- ordered pages
- typed blocks and bounding regions when available
- tables, images, hyperlinks, headers, and footers
- page/document confidence
- provider, requested model, resolved model, and usage
- warnings and provider-native metadata safe for persistence

Provider adapters convert their responses into this model. Rendering and asset
storage consume only the normalized result. Unsupported enrichments are explicit
capabilities, not silently ignored options.

### 4. Keep heavy/self-hosted systems out of process

Do not add Docling, PaddleOCR, olmOCR, or GPU frameworks to the AssistantMD
runtime. Support them through a versioned external HTTP service adapter. MCP may
remain useful for agent-led experiments, but deterministic ingestion should not
depend on an agent tool session being present.

### 5. Select provider transport independently

Mistral accepts a public `document_url`, a base64 data URL, or an uploaded file.
Transport should be selected independently from OCR strategy. There are two
meaningfully different URL-origin flows:

**Direct provider fetch (recommended default for URL OCR)**

1. AssistantMD validates that the source is an allowed HTTP(S) URL and gathers
   enough lightweight evidence to route it as a document when the URL itself is
   ambiguous.
2. It passes the URL to Mistral as `document_url`.
3. Mistral downloads and processes the document directly.

This is the simplest and most efficient path for ordinary public research URLs.
It avoids downloading and then re-uploading the same PDF through AssistantMD.
Content hashing and byte-for-byte provenance are optional capabilities, not
requirements for normal library import.

**AssistantMD fetch and upload (fallback)**

1. AssistantMD validates redirects and downloads the complete response under its
   size/timeout policy.
2. AssistantMD classifies and hashes the exact bytes that will be imported.
3. It sends those same bytes to Mistral, preferably as a raw provider file upload
   rather than base64 JSON, then deletes the temporary provider file.

Use this path when Mistral cannot retrieve the URL, the source requires headers
or credentials that Mistral cannot use, the input is a vault file, or a user
explicitly requests local source capture/provenance.

Local/vault PDFs always use inline base64 below a configurable threshold or file
upload above it. For URLs containing credentials or signed query tokens, the UI
should make clear that direct URL delivery shares the complete URL with the OCR
provider; fetch/upload remains available when that is undesirable.

### URL routing preflight

A preflight is only needed when AssistantMD cannot confidently route the URL by
its suffix or existing source metadata. Many servers reject `HEAD`, omit
`Content-Length`, redirect differently, or mislabel downloads. A bounded routing
preflight may:

1. validate the initial URL and every redirect against the public-network policy;
2. request headers and a small bounded byte range when supported;
3. classify using final URL suffix, `Content-Type`, `Content-Disposition`, and
   payload signatures such as `%PDF`;
4. reject status/auth/block responses and unsupported content;
5. record effective URL, advertised length, classification evidence, and
   preflight timestamp when available;
6. confirm the selected provider supports direct URL input;
7. fall back to AssistantMD fetch/upload when preflight is inconclusive or the
   provider cannot retrieve the URL.

AssistantMD should warn before sending a URL containing embedded credentials or
sensitive query material, but signed URLs may be necessary for Mistral to access
private documents. Users choosing remote OCR are already choosing to disclose
the document content to that provider.

### 6. Make provenance operational

Persist on each ingestion job:

- routing policy and attempted strategies
- selected strategy/provider
- requested and resolved model
- quality decision and fallback reason
- page count, duration, and provider usage where available

Expose the selected strategy/provider in the Import table. This requires a
managed ingestion database migration rather than inferring data from output
files or overloading input options.

## Delivery Stages

Implementation status: Stage 1 is complete. The initial Stage 2 slice now covers
direct provider delivery for explicitly OCR-only public `.pdf` URLs, opt-in
blocks/tables/header/footer/confidence controls, and retention of structured OCR
results as a companion JSON asset. File upload, page ranges, annotations, and
additional source formats remain future work.

### Stage 1: Correctness and observability

1. Fix direct URL OCR option translation.
2. Add a configurable OCR request timeout. Add upload and polling timeouts when
   those transports are introduced.
3. Persist selected strategy/provider/model and expose them through the import
   API and table.
4. Record normalized attempt/fallback reasons without leaking provider payloads.
5. Add scenario coverage for requested versus selected strategy provenance.

### Stage 2: Mistral OCR 4 adapter

1. Parse response model and usage metadata.
2. Support configurable table format, header/footer extraction, confidence, and
   blocks, with conservative defaults.
3. Preserve page structure and normalize images/tables/links.
4. Implement provider transport selection: direct provider URL for URL-origin
   documents by default, with AssistantMD fetch/file-upload fallback and inline
   data for small local payloads. Delete temporary provider files according to
   explicit retention policy.
5. Add selective-page support as an internal capability.

Annotations should remain opt-in and schema-driven. They are valuable for
specialized workflows but should not become part of baseline Markdown import.

### Stage 3: Quality-aware automatic routing

1. Add local PDF profiling and a typed quality decision.
2. Replace non-empty acceptance with policy-driven acceptance.
3. Introduce the user-facing `auto`, `local_text`, `ocr`, and `page_images`
   modes while preserving old strategy-list compatibility.
4. Evaluate local-first versus OCR-first defaults using the validation corpus.

### Stage 4: Provider extensibility

1. Define the external provider protocol and capability declaration.
2. Implement one second provider, recommended Azure Document Intelligence, to
   prove the abstraction.
3. Add a generic external-service adapter for self-hosted PaddleOCR/olmOCR-style
   deployments.
4. Add Adobe, Google, AWS, or Gemini only when user demand justifies their
   credential and normalization complexity.

### Stage 5: Scale features

Consider provider batch APIs, document chunking, and selective-page OCR only
after the synchronous normalized contract and quality routing are validated.
AssistantMD's durable ingestion queue remains the orchestration authority; a
provider batch job is an execution detail, not a second user-facing queue.

## Validation Plan

Extend `import_pipeline_core` and `content_import_tool`, and add a dedicated PDF
strategy-selection scenario if the existing scenarios become too broad.

The retained corpus should include:

- clean born-digital text
- image-only scan
- sparse/broken hidden text layer
- mixed native/scanned pages
- multi-column research paper
- complex table and figure layout
- hyperlinks, headers, footers, equations, and handwriting
- encrypted, malformed, oversized, timeout, and provider-error cases

Contract assertions should cover:

- profiling evidence and deterministic routing decision
- local acceptance versus OCR fallback
- explicit forced-mode behavior
- provider capability validation
- normalized pages/blocks/tables/images/confidence
- selected provider/model provenance in job API, frontmatter, and UI
- preservation of source bytes and vault artifacts on failure

Quality thresholds require human-reviewed corpus results. Maintainers should run
the full validation suite; individual scenarios and provider-mocked contracts
remain agent-owned during implementation.

## Affected Areas

- `core/ingestion/models.py`, `service.py`, and `jobs.py`
- `core/ingestion/strategies/pdf_text.py`, `pdf_ocr.py`, and
  `mistral_ocr_common.py`
- new provider-neutral PDF/OCR policy and adapter modules
- ingestion database schema/migrations
- import API models and services
- Import UI strategy controls and job provenance
- settings/secrets documentation and provider credential bindings
- ingestion architecture docs and ADR 0011 follow-up if the normalized provider
  boundary materially extends that decision

## Next Phase

Proceed to Feature Development with Stage 1 only. Do not begin provider
abstraction or automatic quality thresholds until selected-strategy provenance
and the validation corpus contract are in place.
