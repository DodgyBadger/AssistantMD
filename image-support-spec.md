# Image Content Support Spec and Implementation Plan

## Goal
Add images as a first-class content type in AssistantMD while preserving the existing markdown-first workflow model and composability.

This plan focuses on reusable primitives, not a single hardcoded page-classification pipeline.

## Product Principles
- Keep ingestion deterministic and simple.
- Keep workflow behavior instruction-driven and composable.
- Preserve markdown ergonomics (`.md` default) while enabling explicit non-markdown inputs.
- Avoid over-specializing for "PDF page classification" only.

## Current Constraints (as of 2026-02-23)
- Ingestion is text-first: source importer -> text extractor -> markdown renderer.
- Workflow/context input assumes markdown content and `.md` extension behavior.
- File tooling and output routing are markdown-centric.

## Target Capabilities
1. Ingest PDFs to image pages in vault folders.
2. Reference images directly in directives (`@input file:...png`).
3. Resolve embedded image references inside markdown inputs and attach actual images at runtime.
4. Pass image references through workflow/context machinery without inlining binary.
5. Allow model reasoning over referenced images for flexible tasks:
- workbook lesson extraction
- chapter boundary detection
- photo tagging
- graphics reasoning
- other user-defined image workflows
6. Ingest standalone image files using OCR/text extraction strategies where requested.

## Scope
### In Scope
- `PDF -> page images` ingestion mode.
- Image file ingestion sources (`.png`, `.jpg`, `.jpeg`, `.webp`, optionally `.tiff`).
- Extension-aware `@input file:` behavior.
- Structured image-reference handling in input routing.
- Markdown-embedded image resolution (markdown image tags and wikilinks).
- Optional manifest output for large jobs.

### Out of Scope (for this phase)
- Hardcoded classification logic in ingestion.
- Mandatory image-specific tool for basic read/reference use.
- Changes to context-template execution semantics beyond image refs.

## Proposed Architecture

## 1) Ingestion: Add Image Output Mode
Add ingestion mode choices for PDF jobs:
- `markdown` (existing)
- `page_images` (new)
- `hybrid` (both)

For `page_images` mode, write vault artifacts under configured import output root:
- `Imported/<doc>/pages/page_0001.png ...`
- `Imported/<doc>/manifest.json` (optional but recommended)
- `Imported/<doc>/index.md` (optional human-readable entry point)

### Manifest minimum fields
- source PDF path/name
- page count
- page->image path map
- render parameters (dpi/scale)
- file hash/mtime where practical

Note: Manifest should be metadata only; no assumption of page labels/classification.

### Image files as ingestion sources
Support direct import of image files from `AssistantMD/Import` as first-class sources.

Proposed image strategies:
- `image_ocr` (new): OCR image -> markdown/text artifact.
- `image_copy` (new): store/relocate image artifact without OCR text extraction (for downstream vision workflows).

Provider tie-in:
- Implement `image_ocr` using Mistral OCR (same secret-gated approach as `pdf_ocr`).
- Add settings for image OCR model/endpoint (defaults may mirror existing PDF OCR settings initially).
- Keep strategy ordering configurable (for example `["image_ocr", "image_copy"]`).

### OCR image retention (revisit item)
Current behavior:
- PDF OCR extraction requests text content and does not retain OCR-provided image payloads by default.

Planned revisit:
- Add a configurable OCR ingestion option to retain OCR image outputs when desired.
- Support both:
  - per-run toggle in UI-triggered ingestion (for one-off imports)
  - global default setting in configuration (for recurring behavior)
- Keep default conservative (text-first) unless explicitly enabled, with attachment size/count limits.

## 2) Directive Input: Extension-Aware File Resolution
Update `@input file:` behavior:
- If no extension is provided, default to `.md`.
- If an extension is provided, honor it.
- Add an image handling parameter to control attachment behavior explicitly.

Examples:
- `@input file:notes/today` -> `notes/today.md`
- `@input file:Imported/book/pages/page_0001.png` -> exact image file

This keeps existing templates compatible while enabling explicit image inputs.

### New `@input` image policy parameter
Add optional parameter:
- `images=auto|ignore`

Semantics:
- `auto` (default): include image refs when model/runtime supports multimodal input; otherwise ignore with warning metadata.
- `ignore`: never attach images; treat image references as text/refs only.

Examples:
- `@input file:lesson.md (images=auto)`
- `@input file:lesson.md (images=ignore)`

## 3) Input Payload Model: Text vs Image
For non-text/binary file inputs:
- Do not inline bytes into prompt text.
- Emit structured input records (refs):
  - vault-relative path
  - mime type
  - optional dimensions/hash
  - found/error status

Prompt formatting should include an `IMAGE_REFS`-style section when refs are present.

### Markdown file behavior with embedded images
When input is markdown (`@input file:note.md`), parse and resolve image references from:
- standard markdown image tags: `![alt](path/to/image.png)`
- Obsidian-style embeds/wikilinks: `![[image.png]]`

For each resolvable image reference:
- parse markdown into ordered content chunks (text/image/text/...) rather than separating all text from all images
- preserve image position relative to surrounding text so reasoning stays in local context
- construct multimodal prompt payload as interleaved `UserContent` sequence
  - example shape: `[text_chunk_1, image_1, text_chunk_2, image_2, ...]`
- preserve source mapping (`note.md` chunk/line span -> `image path`) for traceability

For large markdown files with many images:
- keep chunk boundaries explicit (do not flatten to one giant text block)
- apply attachment budgets (count/bytes) over ordered chunks
- when budget is exceeded, spill deferred chunks to buffer/state while preserving ordering metadata
- allow follow-up retrieval by chunk id/range so model can continue exploration without losing positional context

If image refs are broken/missing:
- keep original markdown text and insert an explicit missing-image marker at the same position
- add warning metadata (missing path + source pointer) without failing by default

### Local vs Remote image-ref policy (default assumptions)
To keep reasoning pipelines predictable and safe, prioritize local artifacts over remote fetches.

Default policy:
- local image refs (vault-resolved paths): include by default when `images=auto`
- remote image refs (`http(s)` URLs): keep as refs/URLs by default (no automatic download/attach)

Escalation policy:
- remote image attach is opt-in (explicit user/tool request or strict policy mode)
- when remote attach is enabled, apply strict safeguards:
  - domain allowlist/denylist
  - per-image size limit and download timeout
  - content-type validation
  - max remote image count per step

Budget priority:
- consume attachment budget with local images first
- include remote images only after local budget decisions or explicit selection

Operational note:
- web-search/fetch pipelines should treat remote images as secondary by default; extracted text remains primary unless the step explicitly asks for visual analysis.

### Security posture for image inputs
Image files must be treated as untrusted content, including local files and remote URLs.

Threats to account for:
- crafted image payloads targeting decoder/parser vulnerabilities
- polyglot files (extension says image, content is inconsistent/malicious)
- decompression bombs or oversized media causing resource exhaustion
- hidden/steganographic data and prompt-injection text revealed via OCR

Required safeguards:
- validate media type using magic bytes + parser validation (not extension alone)
- enforce hard limits on file size, dimensions, and decode resource usage
- prefer a sandboxed decode/thumbnail/normalize path for remote or unknown images
- re-encode to safe canonical formats where practical before attachment
- apply network controls for remote fetch (allowlist/denylist, timeout, max bytes, max files)
- treat OCR output and extracted text as untrusted input in downstream reasoning/tool calls

## 4) Agent Runtime: Multimodal Attachment Path
When a step has image refs:
- Attach referenced images to model input for multimodal-capable models.
- Preserve text prompt and markdown refs for traceability.
- If model does not support image input, fail clearly with actionable error.
- Deduplicate repeated references (same image linked multiple times).
- Apply configurable attach limits to avoid unbounded payload size.

## 5) File Tools: Keep Minimal Changes Initially
`file_ops_safe` already provides list/discovery and safe path handling.

Phase-1 approach:
- Keep `file_ops_safe` as primary file explorer.
- Allow safe read/metadata behavior for non-markdown files where needed.
- Do not introduce `image_ops_safe` until there is clear demand for image transforms (resize/crop/exif/etc.).

## Workflow Composition Patterns

## Pattern A: Workbook to Study Program
1. Ingest PDF as `page_images`.
2. Scheduled workflow reads page refs from folder/manifest.
3. LLM generates:
- lesson structure
- chapter boundaries
- study schedule artifacts
4. Context template consumes produced markdown plans for tutoring chat.

## Pattern B: Photo Archive Tagging
1. Images dropped into vault folder.
2. Workflow runs periodically on new files.
3. LLM writes tags/summaries/index markdown.

## Pattern C: Reorganization from Raw Pages
1. Keep raw pages immutable in one folder.
2. Run organization workflow to create chapter/topic subfolders.
3. Re-run only changed/low-confidence ranges using hashes + manifest state.

## Large PDF Operational Guidance (600+ pages)
- Keep ingestion as one-pass deterministic render.
- Process in batched page windows (e.g., 20-50 pages) at workflow level.
- Store intermediate JSON/markdown outputs for resume/retry.
- Avoid global all-pages-in-one-prompt operations.

## JSON as First-Class Automation Artifact
Treat `.json` as first-class for machine-oriented metadata and state.

Guideline:
- `.md` remains default human-authored format.
- `.json` used for manifests, classification outputs, run state, and resumable processing.

## Implementation Plan (Phased)

## Phase 1: Core Image Content Enablement
1. Add ingestion mode for PDF page image extraction.
2. Add image file sources and baseline strategies (`image_ocr`, `image_copy`).
3. Add extension-aware `@input file:` behavior.
4. Add markdown-embedded image reference extraction for `.md` inputs.
5. Add image-reference payload path through input/routing.
6. Add multimodal attachment support in model execution path.
7. Document feature usage and limitations.

## Phase 2: Workflow Templates + Examples
1. Provide sample templates for workbook analysis and photo tagging.
2. Add optional manifest-driven workflow examples.
3. Add guidance for chapter boundary/reorganization workflows.

## Phase 3: Optional Advanced Tooling
1. Evaluate need for dedicated `image_ops_safe`.
2. If needed, include transformation/classification helpers with strict scope.

## Progress Update (2026-02-24)
Status snapshot for current branch work.

Completed:
- Base multimodal prompt plumbing in chat path:
  - chat request supports `image_paths`
  - runtime can send `str | Sequence[UserContent]` to `Agent.run(...)`
  - local vault image paths are attached via `BinaryContent.from_path(...)`
- `file_ops_safe(operation="read")` now supports image files and returns multimodal `ToolReturn` content for vision-capable models.
- Tool auto-buffer routing updated to bypass multimodal `ToolReturn` payloads (prevents accidental buffering of large base64-serialized image content).
- Model capability metadata added across settings/API/config UI:
  - model schema supports `capabilities`
  - configuration tab can view/edit capabilities per model alias
  - capability values are normalized and always include `text`
- Chat runtime now validates image attachments against model `vision` capability.
- PydanticAI integration research captured in this document (API shape, capability caveats, and baseline approach).

Partially complete:
- Non-markdown image handling exists in chat and `file_ops_safe`, but workflow `@input ... (images=...)` path is not yet implemented end-to-end.
- Context-window protection for high image counts is not finalized (interim bypass exists; policy controls still pending).
- Upgrade/migration strategy for existing user `system/settings.yaml` files is intentionally soft:
  - legacy models without explicit `capabilities` remain possible
  - enabling `vision` on existing aliases is currently manual via configuration UI.

Not started (from Phase 1):
- PDF `page_images`/`hybrid` ingestion modes.
- Image ingestion strategies (`image_ocr`, `image_copy`).
- Extension-aware `@input file:` behavior for non-markdown default handling.
- Markdown embedded image ref extraction and attachment in workflow/context pipeline.
- Formal documentation/examples for end users.

Next recommended implementation order:
1. Add targeted validation scenarios for chunked markdown image reads in workflow/context and `file_ops_safe`.
2. Finalize multimodal vs text auto-buffering policy interaction for large multimodal tool outputs.
3. Add ingestion features (`page_images`, `image_ocr`, `image_copy`).
4. Define/implement upgrade assist for existing settings (optional migration helper or UI nudge for missing `vision` capability).
5. Add documentation/examples for end users (including supported file-type policy and `images=auto|ignore` behavior).

## Progress Update (2026-02-25)
Status snapshot for image-chunking work completed after the 2026-02-24 update.

Completed:
- Introduced shared chunking subsystem under `core/chunking`:
  - `markdown.py`: ordered markdown parsing into text/image-ref chunks
  - `prompt_builder.py`: resolves embedded image refs and builds interleaved prompt payloads
  - `policy.py`: settings-backed attachment policy (count/size/remote policy)
- Implemented markdown embedded-image prompt assembly for workflow `@input` path.
- Implemented markdown embedded-image prompt assembly for context-manager `@input` path.
- Added extension-aware `@input file:` resolution behavior:
  - default `.md` only when no extension is provided
  - explicit extension honored
- Added centralized supported file-type policy in `core/constants.py`:
  - single map: extension -> content kind (currently markdown/image)
- Enforced supported file-type policy in:
  - `@input` file loading
  - `file_ops_safe(operation="read")`
- Wired `file_ops_safe(read)` to auto-use chunking for markdown files with embedded image refs:
  - plain markdown without embedded refs remains simple text read
  - markdown with embedded image refs returns multimodal `ToolReturn` content in source order
- Added settings-backed chunking policy controls:
  - `chunking_max_images_per_prompt`
  - `chunking_max_image_mb_per_image`
  - `chunking_max_image_mb_total`
  - `chunking_allow_remote_images`
  - MB-based settings are converted to bytes in accessors; legacy byte-key fallback remains for compatibility.
- Simplified `@input images=` policy modes to:
  - `auto` (default)
  - `ignore`

Behavior notes:
- Remote image URLs remain ref-only by default; no remote download/attach path is implemented yet.
- Image policy no longer has strict modes (`include`/`only`) in this phase.

Still not started:
- PDF `page_images` / `hybrid` ingestion modes.
- Image ingestion strategies (`image_ocr`, `image_copy`).
- Dedicated validation scenarios for chunking/image-policy paths.

## Validation Strategy
- Unit tests for extension resolution and input parsing.
- Unit tests for markdown embedded image parsing and path resolution.
- Unit tests for `images=` policy modes (`auto/ignore`).
- Smoke tests for ingestion output artifacts (`pages/`, `manifest.json`).
- Smoke tests for image-file ingestion (`image_ocr` success/failure, `image_copy` outputs).
- End-to-end scenario:
  - import PDF -> image pages
  - import standalone image -> OCR text output and/or copied artifact
  - workflow consumes direct image refs
  - workflow consumes markdown file containing embedded image refs
  - outputs markdown plan/index
- Failure-path tests for non-vision models and missing files.

## Open Questions
- Exact attachment API shape per provider/model adapter.
- Size limits and downscaling policy for very large images.
- Whether `index.md` is always produced or optional.
- Whether/when to expand `SUPPORTED_READ_FILE_TYPES` beyond markdown/image (for example `.json`) and how to stage that safely.

## Model Capability Metadata
Image handling requires explicit model capability awareness in the provider/model subsystem.

Use a single extensible model field:
- `capabilities: ["text", "vision", ...]`

Design notes:
- Prefer one capabilities list over many booleans.
- Backward compatible default when missing: `["text"]`.
- `@input ... (images=...)` policy should validate against selected model capabilities before execution.
- Runtime/provider adapter remains final authority (defensive check before request send).
- If model lacks required capability:
  - `images=auto`: degrade gracefully with warning metadata.
  - `images=ignore`: do not attempt image attachment.

Future capability examples:
- `text`
- `vision`
- `audio_input`
- `pdf_input`
- `tool_calling`

## PydanticAI Multimodal Integration Notes (Research: 2026-02-24)
These notes capture concrete implementation facts verified against this repo's pinned dependency:
- `pydantic-ai==1.60.0`

### Confirmed prompt API shape
- `Agent.run(...)` accepts either:
  - plain `str` prompt (existing behavior)
  - `Sequence[UserContent]` for multimodal prompts
- `UserContent` supports text plus multimodal objects, including:
  - `BinaryContent` (inline bytes + media type)
  - `ImageUrl` (remote URL image reference)

Minimal working shape:
- `["Describe this image.", BinaryContent.from_path("/abs/path/image.png")]`

This means Phase 1 runtime integration can be implemented without custom provider SDK branches by constructing `Sequence[UserContent]` and passing it through existing `agent.run(...)` calls.

### Image object types to use
- Local vault files:
  - `BinaryContent.from_path(path)` preferred.
  - If media type inference fails, construct `BinaryContent(data=..., media_type=...)` explicitly.
- Remote image URLs (optional later):
  - `ImageUrl(url=...)`, optionally `force_download=True`.

### Important capability-check caveat
- In `pydantic-ai==1.60.0`, there is no single cross-provider `supports_image_input` profile flag to reliably preflight image input support.
- Provider/model adapters perform support checks and mapping at request time.

Implication for AssistantMD:
- Keep `capabilities: ["text", "vision", ...]` in `settings.yaml` as the app-level contract.
- Validate `@input ... (images=...)` policy against AssistantMD model capabilities before calling `agent.run(...)`.
- Keep provider/runtime error handling as a defensive second line (final authority if provider behavior differs from metadata).

### Phase-1 baseline integration target
Before full `@input images=` support, establish this base path:
1. Resolve one explicit image file path.
2. Build prompt as `Sequence[UserContent]` with text + `BinaryContent`.
3. Send through existing agent execution path.
4. Confirm non-vision models fail with actionable error routing.

This base path should be implemented and smoke-tested first, then generalized for image refs extracted from directives/markdown.

### Tool routing interaction discovered during implementation
- Current tool output auto-buffering logic is token-based and text-centric.
- Multimodal `ToolReturn` values (for example, image `BinaryContent`) can serialize to very large base64 strings if treated as plain text.
- If auto-buffering runs on serialized multimodal payloads, image reads are incorrectly routed to buffers and no longer attached inline to the model.

Current patch behavior (accepted as interim):
- Bypass auto-buffer routing when a tool result is `ToolReturn` containing multimodal content parts (`BinaryContent`, `ImageUrl`, etc.).
- Keep multimodal tool payload inline so the model can actually consume image attachments.

Follow-up design task (required before broad rollout):
- Add modality-aware context protection policies so inline image attachments remain bounded.
- Proposed controls:
  - `max_images_per_tool_result` (hard cap per tool call)
  - `max_images_per_step` (aggregate cap across tool calls)
  - `max_image_bytes_per_step` (aggregate byte budget)
  - optional downscale/compression pipeline before attachment
  - dedupe-by-hash for repeated reads of same image
  - policy behavior when limits exceeded (`drop_oldest`, `drop_newest`, `fail`, `summarize_refs_only`)
- Keep text auto-buffering and multimodal attachment limits as separate policy layers (do not reuse text token estimation for binary payload decisions).

## Deferred: Batch Execution Design
Batch is relevant for high-volume image operations but likely conflicts with strict sequential step-engine semantics.

Current position:
- Do not include batch in this phase.
- Specify batch separately after core image content primitives are stable.

Topics for future batch spec:
- whether batch is a new workflow engine vs per-step execution mode
- async run state and resume semantics
- polling/retry/error aggregation
- artifact model (`requests.jsonl`, `results.jsonl`, run state)
- compatibility with existing scheduler and step workflow expectations
