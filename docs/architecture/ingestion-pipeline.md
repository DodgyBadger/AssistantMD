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

URL transport and HTML conversion are implemented as shared primitives under
`core/web/`. URL ingestion adapts those results into `RawDocument` and
`ExtractedDocument`; it does not call the model-facing `web_extract` tool.
Conversely, `web_extract` does not create ingestion jobs or vault artifacts.

## Entry Points

API entrypoints call service helpers exported by `api.services` and implemented
in `api/services/ingestion.py`:

- `/import/scan` -> `scan_import_folder(...)`
- `/import/url` -> `import_url_direct(...)`

`scan_import_folder` walks `AssistantMD/Import` (and legacy `AssistantMD/import`), enqueues supported files, and can process immediately or queue only.

`import_url_direct` enqueues a URL job and processes it immediately for fast feedback.

The configured `content_import` tool submits one or more public HTTP/HTTPS URLs
or vault-relative files as queued jobs. Configured tools are also available as
direct Monty functions, so chat and authored workflows use the same contract.

Immediate API processing runs ingestion jobs inside an execution task with
`task_kind="ingestion"` and `task_source="api"`. Queued worker processing uses
the same execution-task wrapper with `task_source="scheduler"`. Vault writes and
source cleanup therefore flow through the shared vault mutation recorder and
appear in Vault Activity.

## Job Model and Persistence

Jobs are persisted by `core/ingestion/jobs.py` in system database `ingestion_jobs` with status:

- `queued`
- `processing`
- `completed`
- `failed`
- `cancelled`

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

The Dashboard Import Status panel reads durable jobs through `/api/import/jobs`.
Queued jobs can transition atomically to `cancelled` through
`/api/import/jobs/{job_id}/cancel`. `/api/import/run-now` advances and wakes the
existing scheduler job; it does not create a parallel ingestion execution path.
The panel polls while queued or processing work exists.

The shared wrapper lives in `core/ingestion/task_execution.py`; new ingestion
execution paths should use it rather than calling `IngestionService.process_job`
directly from API or scheduler code.

## Service Flow

`IngestionService.process_job(job_id)` executes:

1. Load job and mark `processing`.
2. Resolve source importer:
   - vault-relative files by suffix/mime
   - URLs through bounded transport followed by response classification
3. Branch by source/mode:
   - **detected PDF + `pdf_mode=page_images`**: bypass text extraction and render page images directly.
   - **all other imports**: build strategy order and run extractors until one returns non-empty text.
4. Persist outputs under configured import root.
5. Save output paths and mark `completed` (or `failed` with error).

Built-in handlers are imported for registry side effects in `_load_builtin_handlers()`.

## Strategy Selection and OCR Configuration

Default strategy order:

- URL: `html_markdownify`
- PDF markdown mode: from `ingestion_pdf_default_strategies`, fallback `pdf_text`, `pdf_ocr`
- Image files: from `ingestion_image_default_strategies`, fallback `image_ocr`

URL fetching uses the independently configured
`ingestion_url_fetch_strategy` (`curl` by default). This setting is separate
from `web_extract_strategy`, so choosing a remote provider for agent extraction
does not reroute durable URL imports. The shared curl transport validates the
initial URL and every redirect against the public-network policy and enforces
timeouts and response-size limits.

URL responses retain bytes until classification. Response content type, PDF
payload signature, and URL suffix evidence distinguish HTML from PDF before
strategy selection. Remote PDF bytes use the same PDF strategies as vault
files.

Shared OCR config keys:

- `ingestion_ocr_model`
- `ingestion_ocr_endpoint`
- `ingestion_url_connect_timeout_seconds`
- `ingestion_url_read_timeout_seconds`
- `ingestion_url_max_response_mb`
- `content_import_max_batch_size`

Legacy OCR keys remain accepted as compatibility fallback.

Secret-gated OCR strategies:

- `pdf_ocr` requires `MISTRAL_API_KEY`
- `image_ocr` requires `MISTRAL_API_KEY`

If secrets are missing, the strategy is skipped and warnings are attached to extraction metadata.

## Output Artifacts and Layout

Outputs are stored vault-relative under `ingestion_output_path_pattern` (default
`Imported/`). Markdown files are written directly into that destination.

Current conventions:

- Markdown output: `Imported/<name>.md`
- OCR assets (when enabled): `Imported/assets/<name>/...`
- PDF page-images mode: `Imported/assets/<name>/pages/page_0001.png ...`
- PDF page-images index and metadata: `Imported/<name>.md`

Page-images metadata is stored in the Markdown index frontmatter. Its body links
to each rendered page image.

OCR image persistence controls:

- global setting: `ingestion_ocr_capture_images`
- per-job override: `capture_ocr_images`

When OCR images are persisted, OCR markdown image refs are rewritten to local followable asset paths.

## PDF `page_images` Mode

`pdf_mode=page_images` is a deterministic render path for PDFs.

Behavior:

- applies to PDF inputs only
- bypasses extraction strategies
- writes page images plus a Markdown index with import metadata in frontmatter
- preserves existing scheduler/job model (no separate batch engine)

## Operational Notes

- Registry-backed importer matching limits scan imports to supported types.
- Duplicate queued/processing jobs for the same source are skipped during folder scan.
- Successful batch-inbox imports consume their source file. Vault files
  submitted through `content_import` are preserved.
- URL ingestion logs its selected fetch strategy and timeout context. Logged
  URL identities omit credentials, query strings, and fragments; the durable
  job retains the complete source URL needed for execution.
- Worker executes ingestion pipeline via `asyncio.to_thread(...)` to avoid blocking the event loop.
- Ingestion output writes and source cleanup are audited as task file mutations
  when the job runs through the API or scheduler worker.

## Primary Code

- `api/services/ingestion.py`
- `core/ingestion/service.py`
- `core/ingestion/task_execution.py`
- `core/ingestion/worker.py`
- `core/ingestion/jobs.py`
- `core/ingestion/registry.py`
