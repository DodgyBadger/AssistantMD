# Image Content Support Spec

## Goal

Support images as a first-class content type in AssistantMD while preserving markdown-first ergonomics and composable workflows.

## Product Principles

- Keep ingestion deterministic and simple.
- Keep workflow behavior instruction-driven and composable.
- Preserve `.md` defaults while enabling explicit non-markdown inputs.
- Avoid hardcoded, domain-specific classification behavior in core ingestion.

## Scope

### In Scope

- PDF import mode for rendering page images (`page_images`).
- Image file import support (`.png`, `.jpg`, `.jpeg`, `.webp`, `.tif`, `.tiff`) with OCR strategy support.
- Extension-aware `@input file:` resolution.
- Direct image `@input` usage in workflows/context.
- Markdown embedded-image resolution (`![...](...)`, `![[...]]`) with multimodal prompt assembly.
- Structured policy controls for image attachment (count/size/remote handling).
- Manifest/artifact outputs for large image-oriented ingestion flows.

### Out of Scope

- Hardcoded content classification logic in ingestion.
- Mandatory dedicated image tool for basic read/reference workflows.
- Batch execution engine redesign in this track.

## Normative Requirements

## 1) Ingestion Modes and Sources

- PDF imports MUST support `pdf_mode=markdown|page_images`.
- `page_images` mode MUST apply to PDF files only.
- In `page_images` mode, ingestion MUST bypass text extraction strategies and render deterministic page images.
- `page_images` outputs MUST include:
  - `Imported/<name>/pages/page_0001.png ...`
  - `Imported/<name>/manifest.json`
- `manifest.json` MUST remain metadata-only (no implied classification semantics).
- Ingestion MUST support image files from `AssistantMD/Import` as first-class sources.

## 2) OCR Strategy and OCR Asset Behavior

- Image ingestion MUST support an `image_ocr` strategy.
- OCR integration SHOULD share common request/response parsing plumbing across PDF OCR and image OCR wrappers.
- OCR configuration MUST use shared keys:
  - `ingestion_ocr_model`
  - `ingestion_ocr_endpoint`
- Legacy OCR setting keys MUST remain supported as compatibility fallback.
- OCR image capture MUST be configurable via:
  - global setting: `ingestion_ocr_capture_images`
  - one-shot override: `capture_ocr_images`
- When OCR image assets are persisted, OCR markdown image references MUST be rewritten to local followable paths.

## 3) Output Layout

- Import outputs MUST use per-import folders to avoid naming/path drift.
- Markdown mode output MUST be `Imported/<name>/<name>.md`.
- OCR assets MUST be written under `Imported/<name>/assets/...` when enabled.
- `page_images` artifacts MUST be written under `Imported/<name>/pages/...` plus manifest.

## 4) `@input` File Resolution and Image Policy

- `@input file:<path>` resolution MUST default to `.md` only when no extension is supplied.
- If an extension is supplied, the resolver MUST honor it as-is.
- `@input` image policy modes MUST be limited to:
  - `images=auto` (default)
  - `images=ignore`
- `images=auto` MUST attempt attachment only when policy and model capability allow.
- `images=ignore` MUST never attach images and MUST keep image refs as text markers/refs.

## 5) Supported File-Type Policy

- Supported readable file types for these paths MUST be centrally defined and reused by:
  - `@input` file loading
  - `file_ops_safe(operation="read")`
- Current supported kinds in this track are markdown and image.

## 6) Markdown Embedded Image Semantics

- For markdown inputs, the system MUST resolve embedded image refs from both markdown image syntax and wikilink embeds.
- Prompt assembly MUST preserve source order as interleaved content (text/image/text/...); image order MUST NOT be flattened or regrouped.
- Broken or unresolved refs MUST preserve local context position and produce explicit followable markers.
- Marker forms MUST remain standardized:
  - `[IMAGE REF: <vault-relative-path>]`
  - `[REMOTE IMAGE REF: <url>]`
  - `[MISSING IMAGE: <original-ref>]`

## 7) Remote vs Local Image Policy

- Local vault-resolved images MUST be eligible for attachment under `images=auto` and policy limits.
- Remote `http(s)` image refs MUST remain refs-only by default (no implicit download/attach).
- Any remote attach behavior MUST be explicit opt-in and guarded by:
  - domain allowlist/denylist
  - timeout and max-bytes limits
  - content-type validation
  - max remote image count constraints

## 8) Runtime Capability and Attachment Behavior

- Model metadata MUST include extensible `capabilities` with default compatibility behavior including `text`.
- Vision attachment MUST be gated by model `vision` capability before request send.
- Runtime/provider adapter MUST remain final defensive authority for modality support.
- If model capability is insufficient:
  - `images=auto` MUST degrade gracefully with warning metadata/ref behavior.
  - `images=ignore` MUST continue without attachment attempts.

## 9) Context Protection and Fallback Precedence

- Image handling MUST keep text token protection and multimodal attachment policy as separate layers.
- For markdown-with-images, token-first gating MUST run before image attachment:
  - if text exceeds `auto_buffer_max_tokens`, return refs-normalized text (no image attachments).
- Image preflight MUST be all-or-none per file for configured limits:
  - image count
  - per-image size
  - total image size
- If any preflight guard fails, image attachments MUST be skipped and refs-normalized text returned.
- Policy precedence MUST be deterministic:
  1. token overflow gate
  2. image preflight gate
  3. multimodal attach

## 10) Tooling Decisions

- `file_ops_safe` MUST remain the primary file exploration/read tool in this track.
- `file_ops_safe(read)` MUST support image files and markdown-with-embedded-images multimodal returns.
- Auto-buffer routing MUST NOT treat multimodal `ToolReturn` payloads as plain text for token buffering decisions.
- No LLM-controlled per-call read parameter for image policy is in scope; policy remains centralized and settings-driven.
- A dedicated `image_ops_safe` tool remains deferred unless transform demand is proven.

## 11) Security Requirements

Image inputs (local and remote) MUST be treated as untrusted.

Required safeguards:

- Validate media type using content inspection (not extension alone).
- Enforce hard limits on file size/dimensions/decode resource usage.
- Apply strict network controls for any remote image fetch path.
- Treat OCR output as untrusted text in downstream reasoning/tool flows.

## 12) Validation Requirements

Coverage MUST include:

- extension-aware `@input` resolution behavior.
- markdown embedded-image parsing and ordered multimodal assembly.
- `images=auto|ignore` policy behavior.
- missing/broken image marker behavior.
- `file_ops_safe(read)` parity for markdown/image paths.
- `page_images` ingestion artifact checks (`pages/`, `manifest.json`).
- image-file ingestion (`image_ocr`) success and failure paths.
- non-vision model behavior for image inputs.

## Deferred Design Work

- Modality-aware overflow policies for inline attachments (drop/fail/summarize behavior) are required before broad rollout of high-volume multimodal flows.
- Batch execution architecture remains a separate future spec.
- Image-focused REPL/buffer exploration workflow changes are deferred and should be specified within a broader `buffer_ops`/REPL architecture update, not as a standalone image-track change.
- Image compaction/downscale before attachment is deferred and out of scope for this track.
