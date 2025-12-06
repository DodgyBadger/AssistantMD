# Importer/Ingestion Pipeline – Implementation Plan

## Objectives
- Import non-markdown content (PDF, DOCX, EML; later URLs/APIs) into vault as markdown.
- Keep pipeline pluggable: multiple strategies per format (e.g., PDF text vs. OCR) with configurable ordering.
- Enforce size/token budgets via chunking/condensing to avoid oversized LLM inputs while keeping provenance.
- Reuse artifacts later for embedding/RAG if desired.

## Core Data Shapes
- **RawDocument**: `{source_uri, kind (file|url|api|mail), mime, bytes|text, suggested_title, fetched_at, meta}`.
- **ExtractedDocument**: `{blocks, plain_text, mime, strategy_id, meta (pages/sections, confidence)}`.
- **Chunk**: `{id, parent_id?, order, title, text, offsets/meta (page range, dom path, email part), hash}`.
- **RenderOptions**: `{mode: full|chunked|summary_only, path_pattern, max_tokens_per_chunk, overlap, attachments}`.

## Stages & Responsibilities
1) **Source adapters/importers** (per mime/source):
   - Read/fetch → RawDocument.
   - Examples: `PdfImporter`, `DocxImporter`, `EmlImporter`, `WebPageImporter` (URL + fetch), `ApiImporter` (HTTP request).
2) **Extractors** (registered per mime/strategy):
   - Convert RawDocument to ExtractedDocument.
   - Examples: `PdfTextExtractor`, `PdfOcrExtractor`, `DocxExtractor`, `EmlExtractor`, `HtmlReadabilityExtractor`, `HtmlRawExtractor`.
3) **Segmenter**:
   - Chunk by structure (pages/headings/DOM/email parts) with token or char budgets + overlap.
   - Stable chunk IDs: hash(source_uri + section content + offsets).
4) **Reducer (optional)**:
   - Condense oversized chunks (LLM/rules) but keep links to originals (hash/offsets).
5) **Renderer**:
   - Markdown frontmatter with provenance: `source`, `mime`, `importer`, `strategy`, `fetched_at`, `hash`, `chunk_index/total`, `parent_chunk`, `warnings`.
   - Body: summary + chunk content; link siblings and raw/attachments.
6) **Vault writer**:
   - Path policy e.g., `Imports/{today}/{slug}/index.md`, `chunk_###.md`, `_attachments/<hash>.<ext>`.
   - Collision-safe filenames; optional copy of original binary.
7) **Registry/config**:
   - Simple lookup tables keyed by mime/strategy.
   - Settings to enable/disable strategies, prefer ordering, size limits, OCR toggle, output path pattern.

## Surfaces
- **Web UI Import tab**:
  - Upload files (PDF/DOCX/EML).
  - Submit URLs (single/list) → fetch then ingest.
  - Button per vault: “Scan & ingest `AssistantMD/import/`” (manual trigger; no background watcher). Applies optional sidecar `.import.json` per file for overrides.
  - Job list with status, warnings (e.g., OCR fallback), and links to outputs.
- **API endpoints** (no CLI path needed):
  - `POST /api/import/jobs` for direct uploads/URLs.
  - `POST /api/import/scan` `{vault_id, force?}` to enqueue everything currently in the vault’s import folder.
  - `GET /api/import/jobs` / `/:id` for status/results.
- Lightweight in-app worker (APScheduler or similar) drains the queue with a concurrency limit.

## Proposed Module Structure (backend)
- `core/ingestion/`:
  - `models.py` (RawDocument, ExtractedDocument, Chunk, RenderOptions, Job states)
  - `registry.py` (importer/extractor registries)
  - `pipeline.py` (run_job orchestrator)
  - `segmenter.py`, `renderers.py`, `storage.py` (path policy, attachments)
  - `sources/` (pdf/docx/eml/web/api importers), `strategies/` (pdf_text, pdf_ocr, html_readability)
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
- Golden markdown snapshots for sample PDF/DOCX/EML/HTML.
- Contract tests: every importer returns RawDocument; every extractor handles bad input gracefully.
- Chunker tests for size budgets and stable IDs.
- Integration: end-to-end import of a sample file/URL → expected files on disk.

## Iteration Steps (testable phases)
1) **Scaffold core types + DAL** ✅
   - Add `core/ingestion` with models/registry/pipeline skeleton; job table via `core/database`.
   - Add import constants and path helpers.
   - Unit tests for models/registries/job DAL.
2) **PDF happy path**
   - Implemented PDF importer/extractor end-to-end: scan enqueues jobs from `AssistantMD/import/` and processes via worker.
   - Rendered outputs write to vault-root `Imported/{relative_dir}{slug}/index.md`; preserve subfolders from import source; job outputs are vault-relative.
   - Source files are deleted after successful ingestion; no `_attachments` copy (attachments are dropped and listed in frontmatter).
   - Frontmatter `source_path` is vault-relative (e.g. `AssistantMD/import/foo.pdf`) with warnings for disabled/missing strategies.
   - Text extractor + OCR strategy (config-gated, uses Mistral OCR).
   - Segmenter + renderer (full mode) → writes markdown.
   - Manual verification against sample PDFs; clean ingestion DB.
3) **DOCX/Office support** ✅
   - Office docs (docx/pptx/xlsx): markitdown-based extractor wired as default strategy. Attachments dropped and noted as warnings.
   - Other formats: not ingested by default; users can export to PDF for best fidelity or accept best-effort markitdown where registered.
   - Extend renderer/tests with fixtures (pending).
4) **HTML/web ingestion**
   - Web importer using existing fetch/crawl; readability strategy; chunked render mode.
   - Chunker tests for size budgets and stable IDs.
5) **Job runner + API**
   - Job orchestration (queue, statuses), `POST /api/import/jobs`, `GET /api/import/jobs`, `POST /api/import/scan` (vault import folder trigger).
   - Integration tests: enqueue → process → outputs.
6) **Import folder flow**
   - Implement scan of `AssistantMD/import/` per vault, sidecar overrides, processed/failed moves.
   - Tests for scan/enqueue behavior.
7) **Validation scenarios**
   - Add end-to-end scenarios under `validation/scenarios/` (e.g., PDF happy path, oversize web page chunk/condense, sidecar overrides, failure handling) using BaseScenario helpers; verify outputs, provenance, and job statuses with artifacts captured.
8) **UI**
   - Import tab: upload, URL submit, “scan import folder” button, job list/status/warnings/links.
   - Surface ingestion settings in Configuration UI (enable PDF OCR, default strategies, OCR model/endpoint) and warn when OCR enabled but MISTRAL_API_KEY is missing.
   - Frontend integration with API.
9) **Polish**
   - Error handling, warnings surfaced in frontmatter/status; docs/examples.
