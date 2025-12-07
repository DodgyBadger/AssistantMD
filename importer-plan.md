# Importer/Ingestion Pipeline – Implementation Plan

## Objectives
- Import non-markdown content (PDF, DOCX; later URLs/APIs) into vault as markdown.
- Keep pipeline pluggable: multiple strategies per format (e.g., PDF text vs. OCR) with configurable ordering.
- Keep ingestion simple; segmenting/condensing is a future, standalone capability.
- Reuse artifacts later for embedding/RAG if desired.

## Core Data Shapes
- **RawDocument**: `{source_uri, kind (file|url|api), mime, bytes|text, suggested_title, fetched_at, meta}`.
- **ExtractedDocument**: `{plain_text, mime, strategy_id, blocks?, meta (pages/sections, confidence, warnings)}`.
- **RenderOptions**: `{mode: full, path_pattern, store_original, title, vault, source_filename, relative_dir}`.

## Stages & Responsibilities
1) **Source adapters/importers** (per mime/source):
   - Read/fetch → RawDocument.
   - Examples: `PdfImporter`, `DocxImporter`, `WebPageImporter` (URL + fetch), `ApiImporter` (HTTP request).
2) **Extractors** (registered per mime/strategy):
   - Convert RawDocument to ExtractedDocument.
   - Examples: `PdfTextExtractor`, `PdfOcrExtractor`, `DocxExtractor`, `HtmlReadabilityExtractor`, `HtmlRawExtractor`.
3) **Renderer**:
   - Markdown frontmatter with provenance: `source`, `mime`, `importer`, `strategy`, `fetched_at`, `warnings`.
   - Body: extracted content; link raw/attachments.
4) **Vault writer**:
   - Path policy e.g., `Imports/{today}/{slug}.md`, `_attachments/<hash>.<ext>`.
   - Collision-safe filenames; optional copy of original binary.
5) **Registry/config**:
   - Simple lookup tables keyed by mime/strategy.
   - Settings to enable/disable strategies, prefer ordering, size limits, OCR toggle, output path pattern.

## Surfaces
- **Web UI Import tab**:
  - Upload files (PDF/DOCX).
  - Submit URLs (single/list) → fetch then ingest.
  - Button per vault: “Scan & ingest `AssistantMD/import/`” (manual trigger; no background watcher).
  - Job list with status, warnings (e.g., OCR fallback), and links to outputs.
- **API endpoints** (no CLI path needed):
  - `POST /api/import/jobs` for direct uploads/URLs.
  - `POST /api/import/scan` `{vault_id, force?}` to enqueue everything currently in the vault’s import folder.
  - `GET /api/import/jobs` / `/:id` for status/results.
- Lightweight in-app worker (APScheduler or similar) drains the queue with a concurrency limit; UI-triggered imports can process immediately by default with an opt-in for queueing.

## Proposed Module Structure (backend)
- `core/ingestion/`:
  - `models.py` (RawDocument, ExtractedDocument, RenderOptions, Job states)
  - `registry.py` (importer/extractor registries)
  - `pipeline.py` (run_job orchestrator)
  - `renderers.py`, `storage.py` (path policy, attachments)
  - `sources/` (pdf/docx/web/api importers), `strategies/` (pdf_text, pdf_ocr, html_readability)
  - `jobs.py` (SQLAlchemy models + DAL using `core/database.py`)
- Runtime hook: instantiate ingestion service in `core/runtime/bootstrap.py` and expose via `RuntimeContext`.
- API: import endpoints in `api/endpoints.py` (or `api/import_services.py` for logic) + models.
- Frontend: Import tab in `static/index.html` with JS in `static/app.js` (or `static/js/importer.js`).
- Constants: add import paths (`IMPORT_DIR`, `IMPORT_COLLECTION_DIR`, `_attachments`) to `core/constants.py`.

## Error & Safety
- Allowed MIME/size checks; graceful downgrade to summary-only with warning when limits exceeded.
- Log per stage; propagate warnings into frontmatter/body.
- Keep originals hashed; never execute attachments.

## Testing Strategy
- Golden markdown snapshots for sample PDF/DOCX/HTML.
- Contract tests: every importer returns RawDocument; every extractor handles bad input gracefully.
- Chunker tests for size budgets and stable IDs.
- Integration: end-to-end import of a sample file/URL → expected files on disk.

## Iteration Steps (testable phases)
1) **Scaffold core types + DAL** ✅
   - `core/ingestion` models/registry/pipeline skeleton; job table via `core/database`.
   - Import constants and path helpers.
   - Unit tests for models/registries/job DAL.
2) **PDF happy path** ✅
   - PDF importer/extractor end-to-end: scan enqueues jobs from `AssistantMD/import/` and processes via worker.
   - Rendered outputs write to vault-root `Imported/{relative_dir}{source-name}.md`; preserve subfolders from import source; job outputs are vault-relative.
   - Source files are deleted after successful ingestion; no `_attachments` copy (attachments are dropped and listed in frontmatter).
   - Frontmatter `source_path` is vault-relative (e.g. `AssistantMD/import/foo.pdf`) with warnings for disabled/missing strategies.
   - Text extractor + OCR strategy (config-gated, uses Mistral OCR).
   - Renderer writes markdown; filenames mirror source (slugged for URLs); collision-safe suffixing.
3) **DOCX/Office support** ✅
   - Office docs (docx/pptx/xlsx): markitdown-based extractor wired as default strategy. Attachments dropped and noted as warnings.
   - Other formats: not ingested by default; users can export to PDF for best fidelity or accept best-effort markitdown where registered.
4) **HTML/web ingestion**
   - Build URL importer (fetch + mime sniff) and HTML extractor (readability-first, raw fallback).
   - Use same renderer/storage; record provenance (URL, strategy, warnings).
5) **Job runner + API surface**
   - Expose ingestion as synchronous APIs for URLs/uploads (bypass worker latency): e.g., `POST /api/import/url` runs pipeline immediately and returns `{paths, warnings, cached?, preview?}`.
   - Keep existing `/import/scan` for import-folder jobs; add job list/status endpoints.
   - If we keep the job table for tool/API calls, create job row and run `process_job` inline rather than waiting on the interval worker.
6) **Tooling**
   - Add `ingest_url` tool: inputs `url`, `vault`, optional `mode` (`full|summary_only`), `force`, `inline_preview`, `path_hint`.
   - Tool executes the pipeline synchronously (same code path as APIs), returns vault-relative paths plus optional preview and warnings; respect size/token caps and caching.
7) **Import folder polish**
   - Processed/failed moves, better skip/caching logic.
   - Tests for scan/enqueue behavior and cleanup.
8) **UI**
   - Current: Config tab import scan panel (vault select, extensions, force, results).
   - Next: Upload/URL ingestion UI; job list/status/warnings; expose ingestion settings (OCR, strategies, output path); ensure non-workflow jobs (e.g., ingestion-worker) stay pinned during workflow resync.
9) **Validation scenarios**
   - End-to-end scenarios under `validation/scenarios/` (PDF happy path, web ingestion, sidecar overrides, failure handling); verify outputs/provenance/job statuses with artifacts.
10) **Polish**
   - Error handling, warnings surfaced in frontmatter/status; docs/examples; caching/idempotency (`force` vs reuse), attachment policy.
