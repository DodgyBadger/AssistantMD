# URL Import Fetch Refactor Plan

## Objective
Refactor URL ingestion fetch plumbing to use `curl` as the primary transport while preserving existing user-facing behavior (same API, same output pipeline).

## Current Flow
1. `POST /api/import/url` in `api/endpoints.py` delegates to `import_url_direct(...)`.
2. `import_url_direct(...)` in `api/services.py` enqueues + synchronously processes a URL ingestion job.
3. `IngestionService.process_job(...)` in `core/ingestion/service.py` resolves URL importer.
4. `core/ingestion/sources/web.py::load_url(...)` fetches HTML and returns `RawDocument`.
5. `core/ingestion/strategies/html_raw.py` converts HTML to markdown.
6. Renderer/storage write output to vault.

## Refactor Design

### 1. Isolate Transport
Create a dedicated URL transport module, e.g. `core/ingestion/sources/url_fetchers.py`, containing:
- `UrlFetchResult` data shape (`status_code`, `headers`, `body`, `effective_url`, metadata).
- `fetch_url_with_curl(...)` implementation.
- Optional backend selector entrypoint (`fetch_url(...)`) for future browser backend.

`web.py` should become a thin adapter that:
- Calls fetcher
- Validates blocked statuses (`401/403/429`)
- Decodes text + extracts title
- Returns `RawDocument`

### 2. Make Curl Primary
Implement `fetch_url_with_curl(...)` with `subprocess.run([...], shell=False)`:
- `--location`
- `--max-time` and `--connect-timeout`
- `--silent --show-error`
- `--dump-header` to temp file
- `--output` to temp file

Then parse:
- Final status code (post-redirect)
- Final headers (`content-type`, etc.)
- Body bytes

Map curl failures to actionable runtime errors (timeout/connect/DNS/TLS).

### 3. Keep Service Layer Stable
`core/ingestion/service.py` remains orchestration only:
- Still resolves URL importer through registry
- Still applies strategy/render/store flow unchanged
- No HTTP client logic in service layer

### 4. Settings Shape (Internal)
Keep URL fetch config under ingestion settings, with explicit keys:
- `ingestion_url_read_timeout_seconds`
- `ingestion_url_connect_timeout_seconds`
- `ingestion_url_fetch_backend` (default: `curl`)

Even if only `curl` is implemented now, backend key prevents another refactor when browser backend lands.

### 5. Future Backend Path
Add backend contract now so headless-browser fetch can be slotted in later:
- `python` (optional), `curl` (default), `browser` (future)
- Selection in one place (fetcher module), not spread across service/importer

### 6. Validation Plan
Add tests covering:
- Curl command assembly
- Redirect/header parsing correctness
- Error mapping by curl exit code
- Max-bytes guardrail handling

Add one integration scenario for URL import with known page(s).

## Execution Sequence
1. Introduce `url_fetchers.py` with curl fetch + parse helpers.
2. Simplify `web.py` to call fetcher and build `RawDocument`.
3. Wire any needed URL settings in `IngestionService._get_ingestion_settings()`.
4. Add/adjust tests.
5. Manual smoke on problematic URL + normal URLs.

## Non-Goals
- No API contract changes.
- No user workflow changes.
- No extractor/renderer/storage behavior changes.
