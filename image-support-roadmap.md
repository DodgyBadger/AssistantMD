# Image Support Roadmap (Current)

This roadmap reflects the implemented direction and decisions through 2026-02-28.

## 1) Model + Runtime Multimodal Foundation
- ✅ Add model capability metadata (`capabilities`) with normalized defaults including `text`.
- ✅ Gate image attachment on `vision` capability in runtime/chat path.
- ✅ Support multimodal prompt payloads (`str | Sequence[UserContent]`) and local image attachment via `BinaryContent`.
- ✅ Keep provider/runtime as final defensive authority even after app-level capability checks.
- ⬜ Add modality-aware attachment limits at runtime (per tool call/per step/image bytes).

## 2) Input Semantics and Routing
- ✅ Make `@input file:` extension-aware:
  - no extension -> default `.md`
  - explicit extension -> honor as-is
- ✅ Support direct image inputs in workflow/context (`@input file:foo.png`) when policy allows.
- ✅ Simplify image policy modes to `images=auto|ignore` (drop earlier strict modes).
- ✅ Implement markdown embedded-image parsing and ordered interleaving of text + images.
- ✅ Keep missing/unresolved refs in-place with explicit markers and warning metadata.
- ✅ Centralize supported file-type policy (markdown/image) and enforce in both `@input` and `file_ops_safe(read)`.
- ✅ Keep remote image refs as refs-only by default (no automatic download/attach).
- ⬜ Implement opt-in remote image fetch/attach path with allowlist/limits/timeouts/content-type validation.

## 3) Context Protection and Fallback Behavior
- ✅ Add token-first gate for markdown-with-images:
  - if text exceeds `auto_buffer_max_tokens`, return refs-normalized text (no image attach)
- ✅ Add all-or-none image preflight gate:
  - if any image guard fails (count/per-image/total), attach none and return refs-normalized text
- ✅ Standardize followable degraded markers (`[IMAGE REF]`, `[REMOTE IMAGE REF]`, `[MISSING IMAGE]`).
- ✅ Keep policy precedence deterministic: token gate -> image preflight -> multimodal attach.
- ✅ Keep text auto-buffering separate from multimodal handling.
- ✅ Bypass text-centric auto-buffer routing for multimodal `ToolReturn` payloads to prevent accidental base64 buffering.
- ✅ Keep multimodal overflow fallback simple and behaviorally consistent:
  - default remains all-or-none `refs-only` fallback (drop-all attachments for the gated input)
  - do not introduce partial keep/drop policies by default (`drop_oldest`/`drop_newest`) to avoid biased retention signals
  - align fallback semantics with auto-buffer exploration (text + followable refs first)

## 4) Ingestion and Artifact Layout
- ✅ Add PDF ingestion mode selector: `markdown` vs `page_images`.
- ✅ Implement `page_images` output:
  - `Imported/<name>/pages/page_0001.png ...`
  - `Imported/<name>/manifest.json`
- ✅ In `page_images` mode, bypass text-extraction strategies for PDFs.
- ✅ Add image-source ingestion support (`.png`, `.jpg`, `.jpeg`, `.webp`, `.tif`, `.tiff`).
- ✅ Add dedicated `image_ocr` strategy.
- ✅ Refactor to shared OCR integration path (common request/response parsing).
- ✅ Consolidate OCR settings to shared keys (`ingestion_ocr_model`, `ingestion_ocr_endpoint`) with legacy fallback.
- ✅ Add OCR image capture controls:
  - global: `ingestion_ocr_capture_images`
  - one-shot import override: `capture_ocr_images`
- ✅ Persist OCR image assets and rewrite OCR markdown image refs to local followable paths.
- ✅ Standardize per-import folder layout (including assets) through shared output-path helper.

## 5) Tooling and Surface Area Decisions
- ✅ Keep `file_ops_safe` as the primary file tool for now.
- ✅ Extend `file_ops_safe(read)` to support image files and markdown-with-images multimodal returns.
- ✅ Do not add `image_ops_safe` in this track; revisit only if image transforms become a real need.
- ✅ Do not add an LLM-controlled `file_ops_safe(read)` image-policy parameter; keep policy centralized/settings-driven.

## 6) Validation and Docs
- ✅ Add validation coverage for direct image inputs, `file_ops_safe(read)` image reads, `images=ignore`, and missing-image markers.
- ✅ Update user and architecture docs for image inputs, routing behavior, and multimodal design.
- ⬜ Add/complete targeted stress validation for large multimodal payload protection (high image count/size scenarios).

## 7) Deferred / Explicitly Out of Current Track
- ✅ Keep batch execution design deferred until core image primitives and policy controls are stable.
- ✅ Keep markdown-first ergonomics as default while enabling explicit non-markdown inputs.
- ✅ Defer image-specific REPL/buffer exploration mechanics and address them as part of a broader `buffer_ops`/REPL behavior upgrade package.
- ✅ Defer image compaction/downscale work for this track (not planned unless future evidence shows size-based gates are a real bottleneck).
