# Ingestion Pipeline

This page explains how AssistantMD imports files/URLs into vault artifacts.

## Sources vs Strategies (Core Model)

The ingestion pipeline has two main stages for text-oriented imports:

- **Source importer**: reads raw input and produces a `RawDocument` (for example, PDF/image bytes from `AssistantMD/Import` or HTML fetched from a URL).
- **Extraction strategy**: converts that raw document into usable text (`ExtractedDocument`) using one or more strategy functions.

In short: importers answer **"how do we load this source?"** and strategies answer **"how do we extract text?"**

Examples:

- URL import: source importer fetches HTML, strategy `html_markdownify` extracts markdown text.
- PDF import (`pdf_mode=markdown`): source importer loads PDF bytes, then strategies (for example `pdf_text`, then `pdf_ocr`) run in order until one succeeds.
- Image import: source importer loads image bytes, strategy `image_ocr` extracts text via OCR.

## Entry Points

API entrypoints call service helpers in `api/services.py`:

- `/import/scan` -> `scan_import_folder(...)`
- `/import/url` -> `import_url_direct(...)`

`scan_import_folder` walks `AssistantMD/Import` (and legacy `AssistantMD/import`), enqueues supported files, and can process immediately or queue only.

`import_url_direct` enqueues a URL job and processes it synchronously for fast feedback.

## Job Model and Persistence

Jobs are persisted by `core/ingestion/jobs.py` in system database `ingestion_jobs` with status:

- `queued`
- `processing`
- `completed`
- `failed`

Key fields include source URI, vault, source type, options, error, and output file list.

Important options used by current image/PDF flows include:

- `pdf_mode`: `markdown` (default) or `page_images` for PDF imports.
- `capture_ocr_images`: one-shot override for OCR image-asset persistence.

## Runtime Wiring

`bootstrap_runtime` initializes:

- `IngestionService`
- `IngestionWorker`
- APScheduler interval job (`ingestion-worker`)

Worker scheduling is driven by settings:

- `ingestion_worker_interval_seconds`
- `ingestion_worker_batch_size` (mapped to worker max concurrent jobs)

## Service Flow

`IngestionService.process_job(job_id)` executes:

1. Load job and mark `processing`.
2. Resolve source importer:
   - files by suffix/mime
   - URLs by scheme/mime fallback
3. Branch by source/mode:
   - **PDF + `pdf_mode=page_images`**: bypass text extraction and render page images directly.
   - **all other imports**: build strategy order and run extractors until one returns non-empty text.
4. Persist outputs under configured import root.
5. Save output paths and mark `completed` (or `failed` with error).

Built-in handlers are imported for registry side effects in `_load_builtin_handlers()`.

## Strategy Selection and OCR Configuration

Default strategy order:

- URL: `html_markdownify`
- PDF markdown mode: from `ingestion_pdf_default_strategies`, fallback `pdf_text`, `pdf_ocr`
- Image files: from `ingestion_image_default_strategies`, fallback `image_ocr`

Shared OCR config keys:

- `ingestion_ocr_model`
- `ingestion_ocr_endpoint`

Legacy OCR keys remain accepted as compatibility fallback.

Secret-gated OCR strategies:

- `pdf_ocr` requires `MISTRAL_API_KEY`
- `image_ocr` requires `MISTRAL_API_KEY`

If secrets are missing, the strategy is skipped and warnings are attached to extraction metadata.

## Output Artifacts and Layout

Outputs are stored vault-relative under `ingestion_output_path_pattern` (default `Imported/`) using per-import folders.

Current conventions:

- Markdown output: `Imported/<name>/<name>.md`
- OCR assets (when enabled): `Imported/<name>/assets/...`
- PDF page-images mode: `Imported/<name>/pages/page_0001.png ...`
- PDF page-images manifest: `Imported/<name>/manifest.json`

`manifest.json` is metadata-only and is intended for orchestration/resume workflows (no built-in classification semantics).

OCR image persistence controls:

- global setting: `ingestion_ocr_capture_images`
- per-job override: `capture_ocr_images`

When OCR images are persisted, OCR markdown image refs are rewritten to local followable asset paths.

## PDF `page_images` Mode

`pdf_mode=page_images` is a deterministic render path for PDFs.

Behavior:

- applies to PDF inputs only
- bypasses extraction strategies
- writes page images plus manifest artifacts
- preserves existing scheduler/job model (no separate batch engine)

## Operational Notes

- Registry-backed importer matching limits scan imports to supported types.
- Duplicate queued/processing jobs for the same source are skipped during folder scan.
- URL ingestion logs backend/timeouts and records detailed failure metadata.
- Worker executes ingestion pipeline via `asyncio.to_thread(...)` to avoid blocking the event loop.

## Primary Code

- `api/services.py`
- `core/ingestion/service.py`
- `core/ingestion/worker.py`
- `core/ingestion/jobs.py`
- `core/ingestion/registry.py`
