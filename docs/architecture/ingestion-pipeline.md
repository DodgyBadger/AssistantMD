# Ingestion Pipeline

This page explains how AssistantMD imports files/URLs into vault markdown.

## Sources vs Strategies (Core Model)

The ingestion pipeline has two distinct stages:

- **Source importer**: reads raw input and produces a `RawDocument` (for example, a PDF file from `AssistantMD/Import` or HTML fetched from a URL).
- **Extraction strategy**: converts that raw document into usable text (`ExtractedDocument`) using one or more strategy functions.

In short: importers answer **"how do we load this source?"** and strategies answer **"how do we extract text from it?"**

Examples:

- URL import: source importer fetches HTML, strategy `html_markdownify` extracts markdown text.
- PDF import: source importer loads PDF bytes, strategies (for example `pdf_text`, then `pdf_ocr`) run in order until one succeeds.
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

## Runtime Wiring

`bootstrap_runtime` initializes:

- `IngestionService`
- `IngestionWorker`
- APScheduler interval job (`ingestion-worker`)

Worker scheduling is driven by general settings:

- `ingestion_worker_interval_seconds`
- `ingestion_worker_batch_size` (mapped to worker max concurrent jobs)

## Service Flow

`IngestionService.process_job(job_id)` executes:

1. Load job and mark `processing`.
2. Resolve source importer:
   - files by suffix/mime
   - URLs by scheme/mime fallback.
3. Build strategy order:
   - URL default: `html_markdownify`
   - PDF defaults from settings (`ingestion_pdf_default_strategies`), fallback `pdf_text`, `pdf_ocr`.
   - Image defaults from settings (`ingestion_image_default_strategies`), fallback `image_ocr`.
4. Run extractors in order until one returns non-empty text.
5. Render to markdown and store output under configured base path (when `ingestion_ocr_capture_images=true`, OCR image payloads are persisted under `<import-name>_assets/`).
6. Save output paths and mark `completed` (or `failed` with error).

Built-in handlers are imported for registry side effects in `_load_builtin_handlers()`.

## Strategies and Secrets

Current secret-gated strategy:

- `pdf_ocr` requires `MISTRAL_API_KEY`
- `image_ocr` requires `MISTRAL_API_KEY`

If required secrets are missing, the strategy is skipped and warnings are attached to extraction metadata.

## Output Path Behavior

Rendered outputs are stored vault-relative using `RenderOptions.path_pattern`, driven by setting:

- `ingestion_output_path_pattern` (default `Imported/`)

When source files are under import subfolders, relative structure is preserved in outputs.

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
