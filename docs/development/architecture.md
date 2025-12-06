# AssistantMD Architecture (Quick Reference)

AssistantMD is designed as a **single-user application** that runs locally or on a private server where a user’s markdown “vaults” are synced.

## System Snapshot

```
FastAPI app (api/) 
    ↓ lifespan bootstrap
Runtime context (core/runtime/) 
    ↓ schedules & vault metadata
Scheduler (APScheduler + SQLAlchemy job store) 
    ↓ job triggers
Workflows (workflows/) 
    ↓ directives & LLM calls
Vault files (data/) + system logs (system/)
```

The browser-based chat UI (served from `static/`) talks to the API layer, which routes requests through the same runtime context and LLM interfaces used by scheduled workflows.

## Core Runtime Loop

1. **FastAPI lifespan** constructs a `RuntimeConfig` and calls `bootstrap_runtime`, wiring together the scheduler, workflow loader, and logging under a shared runtime context.
2. **Workflow discovery** (via `core/workflow/`) scans vaults for workflow markdown files (including subfolders one level deep, ignoring underscore-prefixed folders), parses configuration, and prepares schedule triggers for enabled workflows.
3. **Scheduler synchronization** (in `core/scheduling/`) compares configured workflows with persisted jobs to add, update, or remove APScheduler entries without resetting timing unnecessarily.
4. **Workflow execution** kicks off when a trigger fires: the workflow receives lightweight `job_args`, instantiates `CoreServices`, processes directives, gathers context, and calls the LLM interface.
5. **Outputs & state** are written back to the vault, state trackers update `{pending}` metadata, and activity logging records the run.

## Subsystems at a Glance

| Area | Responsibility | Stable modules/directories |
| --- | --- | --- |
| API | REST endpoints, exception wiring, web UI hosting | `api/`, `main.py` |
| Chat UI | Static single-page app that drives chat sessions through API endpoints | `static/`, `api/endpoints.py`, `core/llm/chat_executor.py` |
| Runtime | Configuration, bootstrap, global context, scheduler lifecycle, configuration reload service, path helpers | `core/runtime/`, `core/runtime/reload_service.py`, `core/runtime/paths.py`, `core/constants.py` |
| Workflow Loader | Vault discovery, workflow parsing, trigger preparation | `core/workflow/` |
| Scheduler | Job syncing, picklable job args, trigger comparison | `core/scheduling/` |
| Workflow Layer | Step orchestration, directive processing, file writes | `workflows/`, `core/core_services.py` |
| Directive System | Parse/process `@directives`, pattern resolution, file state | `core/directives/`, `core/workflow/parser.py` |
| LLM Interface | Model resolution, agent creation, response generation | `core/llm/`, `core/settings/store.py` |
| Tools & Models | Tool backends, configuration-driven lookup | `core/tools/`, `core/settings/settings.template.yaml` (seed) |
| Logging & Activity | Unified logging, Logfire instrumentation | `core/logger.py/`, `system/activity.log` |
| Validation | Scenario-based end-to-end checks | `validation/` |
| Ingestion | File import pipeline (PDF/Mistral OCR, markitdown DOCX), registry-driven strategies, queued worker | `core/ingestion/`, `api/services.py` |

## Workflows & Directives

- The system currently ships with the **step** workflow engine (`workflow_engines/step/`), which discovers all `##` headings (e.g. `## STEP 1`, `## STEP 2`, etc.), processes directives with `CoreServices.process_step`, and executes them sequentially.
- Additional workflow engines can be added under `workflow_engines/<name>/` as long as they expose an `async def run_workflow(job_args: dict, **kwargs)` entry point.
- Directives are resolved centrally by `core/directives/` and the helper functions in `core/workflow/parser.py`. Each directive processor is a parser: it validates input, resolves patterns, and returns structured data. Workflows decide how (or whether) to use that data, keeping directive logic decoupled from workflow behavior. Features like `{pending}` tracking are implemented via `WorkflowFileStateManager`, but the workflow determines when state updates occur.

## LLM, Models, and Tools

- Model aliases and provider requirements live in `core/settings/settings.template.yaml` (seeded to `system/settings.yaml`) and are loaded through `core/settings/store.py`. `core/llm/` handles API key  checks, agent creation, and response generation.
- Tools are configured alongside models in `core/settings/settings.template.yaml`. The `@tools` directive loads the referenced classes from `core/tools/`, injects vault context, and augments agent instructions.

## Observability & Validation

- `UnifiedLogger` instruments FastAPI, APScheduler, and Pydantic AI while writing structured activity entries to `system/activity.log`.
- The validation framework (`validation/`) spins up isolated runtimes, runs workflows against sandbox vaults, and captures artifacts for review.

## Configuration Services

- `core/settings/` provides typed access to infrastructure configuration via `AppSettings`, aggregates configuration health with `ConfigurationStatus`, and exposes helpers the API uses to gate unavailable tools and models.
- `core/settings/store.py` loads `system/settings.yaml` (seeded from `core/settings/settings.template.yaml`) as validated Pydantic models for tools, providers, model aliases, and general settings. Secrets are persisted in `system/secrets.yaml` via `core/settings/secrets_store.py`, which offers  atomic read/write helpers for the API and UI.
- `core/runtime/reload_service.py` centralizes hot reload behaviour: it refreshes settings caches, updates the runtime context’s `last_config_reload` timestamp, and returns configuration status so API endpoints can signal when a restart is still required.

## Ingestion Pipeline

- `api/services.py` exposes `/api/import/scan` to enqueue files from `AssistantMD/import/` per vault; jobs persist in `ingestion_jobs.db`.
- `core/ingestion/` hosts the pipeline: source loaders (`sources/`), extractors (`strategies/`), segmenter/renderer/storage, and a registry that maps MIME/strategy ids to functions.
- `IngestionService` resolves strategies per job (defaults from settings, per-job overrides), skips unsupported or missing-secret strategies with warnings, and runs extractors in order until one returns text.
- PDF: default strategies are PyMuPDF text, then optional Mistral OCR (`ingestion_pdf_enable_ocr`, `ingestion_pdf_ocr_model/endpoint`, requires `MISTRAL_API_KEY`); frontmatter records source_path, strategy, warnings, dropped attachments.
- DOCX: markitdown-based extractor (`docx_text`) is the default; attachment binaries are dropped and listed in warnings. Other formats are not ingested by default (users should export to PDF).
- Worker: `IngestionWorker` runs in APScheduler, offloading jobs via `asyncio.to_thread`; outputs are written vault-relative under `Imported/...`, and source files are removed after success to keep import folders clean.

## When the Code Changes

- Minor file moves rarely affect these boundaries; if a module is renamed, it will still sit inside the same directory listed above.
- For detailed behavior or implementation questions, ask a coding agent to inspect the relevant module (for example, “explain how CoreServices processes directives”). This keeps the documentation short while ensuring timely, code-level answers.
