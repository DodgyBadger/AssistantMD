# Content Import Tool Implementation Plan

## Implementation Status

Implemented on `dev/research-automation`:

- explicit preserve/consume source disposition with cleanup removed from storage
- vault-relative file ingestion outside `AssistantMD/Import`
- byte-preserving remote HTML/PDF classification and routing
- URL provenance in rendered markdown
- shared singular/batch submit and status service
- settings-backed `content_import` tool with direct Monty binding
- editable batch and URL response-size limits
- removal of the obsolete `import_content` authoring helper
- focused validation scenarios and architecture/tool documentation

Local smoke probes and the complete Ruff, Black, and MyPy quality gate pass.
Targeted harness scenarios and the maintainer-owned full validation suite remain
to be run by maintainers before delivery is considered validated.

## Objective

Provide one focused, settings-backed tool that chat agents and Monty workflows
can use to trigger durable import-to-markdown for one source or a batch of
sources.

The tool does not discover sources, maintain research state, organize a library,
or decide what should be imported. Users can compose it through direct chat
instructions, skills, playbooks, vault markdown, `goal_ops`, or deterministic
Monty workflows.

The implementation must make ingestion source-agnostic enough to accept:

- remote HTTP/HTTPS URLs
- vault-relative files anywhere in the active vault
- the existing `AssistantMD/Import` batch inbox through its current UI/API
  adapter

Initial remote content support is HTML and PDF. Existing local PDF and image
support remains available. Additional formats and extraction providers remain
registry extensions, not requirements for this effort.

## Public Contract

### Configured tool

Add a configured tool named `content_import`. Because configured tools are
already bound as direct async functions in Monty, chat and authoring scripts use
the same tool schema and result contract.

Initial operations:

- `submit`: enqueue one source or a batch for durable ingestion
- `status`: return current job state for one job id or a batch of job ids

Conceptual signature:

```python
content_import(
    *,
    operation: str,
    sources: str | list[str] | None = None,
    job_ids: int | list[int] | None = None,
    options: dict | None = None,
)
```

Contract rules:

- `submit` requires `sources` and rejects `job_ids`.
- `status` requires `job_ids` and rejects `sources`.
- A source is either an HTTP/HTTPS URL or a vault-relative file path.
- Absolute file paths, path traversal, virtual mounts, unsupported URL schemes,
  empty batches, and mixed invalid arguments fail at the tool boundary.
- Batch size is bounded by an editable setting to keep tool calls and job
  creation predictable. The default is 20 sources.
- Options are validated against a small allowlist before jobs are created.
- Submission does not define research deduplication, retry, or resumption
  policy. Each accepted source creates an ingestion job.
- Status lookup is by job id and is restricted to the active vault.

Initial allowed options should reuse current ingestion contracts:

- `pdf_mode`: `markdown` or `page_images`
- `strategies`: optional ordered extraction strategy ids
- `capture_ocr_images`: optional boolean override
- `clean_html`: optional boolean

Do not expose arbitrary nested extractor options through the model-facing
schema. Translate the validated public options into existing internal job
options.

Operational limits such as batch size, fetch timeouts, response-size limits,
and future bounded-wait timeouts belong in editable settings with conservative
defaults. They are deployment policy, not ad hoc model-selected options. Reuse
the existing ingestion URL timeout settings where they already own the
behavior; add new settings only for limits that do not yet have an owner.

### Per-source result

Both operations return one structured item per source/job with:

- `job_id`
- `source`
- `source_kind`: `url` or `vault_file`
- `status`: `queued`, `processing`, `completed`, or `failed`
- `outputs`: vault-relative output paths
- `error`: safe failure text when present

The tool return should include concise model-readable text plus the structured
items in metadata so chat and Monty do not need to parse prose to inspect job
ids or output paths. Do not add classification, manual-intervention, research
progress, or provider policy fields until a concrete caller needs them.

### Execution behavior

`submit` creates durable queued jobs and returns promptly. Existing ingestion
worker scheduling processes them through ingestion execution tasks. The tool
does not wait indefinitely for OCR or large batches.

`status` is read-only. Agents and workflows decide if and when to call it.

A bounded wait operation is outside the initial contract. It can be added later
without changing job submission if real usage demonstrates the need.

## Current Implementation Findings

### Source resolution is coupled to the inbox

`core/ingestion/service.py` resolves every non-URL relative source under
`AssistantMD/Import` and falls back to the legacy lowercase inbox. Jobs do not
currently distinguish an inbox-relative name from a vault-relative path.

Refactor file jobs to persist a vault-relative source path. The inbox scanner
should enqueue `AssistantMD/Import/<name>` rather than only `<name>`. Source
resolution must validate the persisted path against the job vault before any
file read.

### Cleanup is coupled to storage

`core/ingestion/storage.py` deletes `RenderOptions.source_filename` after
writing whenever that path is inside the vault. Page-image mode separately
deletes its source in `IngestionService`. This makes arbitrary vault-file import
unsafe and gives storage responsibility for source lifecycle.

Remove all source deletion from storage. Make source disposition an explicit
job option owned by ingestion orchestration:

- `consume_source=true` only for the `AssistantMD/Import` scan adapter
- `consume_source=false` for `content_import` vault paths and URLs

After all artifacts are stored successfully, `IngestionService` performs one
centralized, audited cleanup step only when the validated job disposition is
consumptive. Cleanup failure remains non-fatal but must be logged with job and
source context.

### URL ingestion assumes HTML

`core/ingestion/sources/web.py` decodes every successful response as UTF-8 and
defaults missing media type to HTML. `IngestionService._get_strategies()` then
selects `html_markdownify` for every URL, regardless of response media type.
The direct URL API also forces a `text/html` hint.

Refactor URL loading to retain response bytes and transport metadata. Determine
the effective media type from bounded, deterministic evidence:

1. response `Content-Type`
2. PDF payload signature (`%PDF`)
3. final/requested URL suffix as a fallback
4. HTML as the default only when the payload is plausibly text/HTML

Return one `RawDocument` with the requested URL as provenance, final URL and
response metadata in `meta`, detected MIME, byte payload, and a deterministic
suggested title. HTML extraction already accepts byte payloads. PDF bytes can
therefore use the existing PDF strategies without a temporary file.

Strategy selection must use the loaded document MIME rather than the job's URL
source type. PDF page-image mode must likewise key off detected PDF MIME rather
than a local filename suffix.

Unsupported response types should fail explicitly after loading; they must not
be rendered as garbled HTML.

### Job persistence is sufficient for v1

The current ingestion job row already stores source URI, vault, source type,
MIME hint, options, status, error, outputs, and timestamps. The narrow tool does
not require durable batch records, source identities, new statuses, or research
metadata.

Use existing fields for v1:

- persist vault-relative file path in `source_uri`
- retain `source_type` values `file` and `url`
- store validated source disposition and extraction options in `options`

No ingestion database schema migration is planned. If implementation reveals a
required durable field, ingestion jobs must first be brought under the
centralized system migration framework; do not rely on SQLAlchemy
`create_all()` to evolve an existing database.

### Rendering and output behavior stay stable

Keep the current markdown renderer, OCR asset handling, configured output root,
per-import directory naming, collision suffixing, and vault-mutation routing.
Research-level duplicate prevention is not part of this tool.

One renderer correction is needed: remote provenance in frontmatter should
preserve a useful source URL rather than treating it as a filesystem path or
reducing it to `os.path.basename`. Define and validate that output contract in
the URL scenario before changing rendering fields.

### Existing `import_content` helper is obsolete

`core/authoring/helpers/import_content.py` is an unimplemented placeholder with
a singular-source signature. The current authoring runtime automatically binds
configured tools as Monty functions.

Remove the placeholder capability, its registration/contract entry, and its
stub when `content_import` lands. Do not retain two script-facing names for the
same behavior unless released compatibility evidence is found during
implementation.

## Internal Design

### Source request model

Introduce a small typed internal request rather than passing loosely shaped
dictionaries through API, tool, and ingestion code. It should capture:

- source value
- classified source kind
- vault-relative path when applicable
- validated ingestion options
- source disposition (`preserve` or `consume`)

The model is an application/service contract, not a new persisted research
object.

### Shared submission and serialization service

Add shared functions near ingestion ownership, rather than teaching API code or
the tool to construct raw jobs independently. Responsibilities:

- classify URL versus vault-relative path
- validate vault paths using the existing realpath/symlink boundary pattern,
  without the markdown-only restriction used by ordinary file tools
- validate and translate public options
- enqueue one job per accepted source
- serialize jobs into the stable per-source result
- retrieve jobs by id and enforce vault ownership

The exact module may be `core/ingestion/import_service.py` or an expansion of
`IngestionService`. Prefer a separate application-level module if keeping batch
validation, vault binding, and serialization inside `IngestionService` would
further enlarge its already monolithic processing method.

Do not put HTTP response classification or extraction strategy mechanics in the
tool adapter.

### Failure boundaries

- Whole-call argument errors return a structured tool failure with no jobs
  created.
- For a valid batch, validate every source before creating any jobs so a typo
  does not produce a partial batch unexpectedly.
- Once jobs are accepted, each job fails independently through existing durable
  job state.
- `status` reports unknown or cross-vault ids as structured failures without
  exposing another vault's job metadata.
- Tool failures follow `core.tools.failures` conventions so Monty converts
  actual tool failures to `RuntimeError`, while successfully submitted jobs that
  later fail remain ordinary domain results visible through `status`.

### Security and authority

- Bind the tool to the active `vault_path`; callers do not supply a vault name.
- Resolve the bound vault path under configured `data_root` using the same
  containment standard as other vault-bound tools.
- Reject symlink escapes and arbitrary host paths before enqueueing.
- Continue using shared curl public-network policy, redirect validation,
  response limits, and timeouts for URLs.
- Read tool and ingestion operational limits from editable settings. Invalid
  configured limits fail configuration health/startup checks rather than being
  silently accepted at tool execution time.
- Sanitize URL identities in logs while retaining the executable source in the
  durable job.
- Worker processing retains scheduler execution-task attribution. Tool
  submission itself should emit a validation event attributed to the calling
  tool; it does not need to run ingestion inside the chat task.

## API and UI Compatibility

The new tool is the deliverable. UI redesign is not required in the first
implementation, but existing import behavior must remain correct through the
refactor.

- Keep `/api/import/scan` request and response contracts.
- Keep `AssistantMD/Import` scanning and consume-after-success behavior.
- Keep `/api/import/url` as a single-source immediate import for compatibility,
  but route its job construction through the shared validation/submission
  service and stop forcing an HTML MIME hint.
- Keep current Import UI behavior unless the shared response contract requires
  a small adapter change.

Multiline URL UI, generalized API batches, and Vault Explorer Import/Convert are
follow-up surfaces over the same shared service. They are intentionally outside
the initial `content_import` delivery.

## Extraction Strategy Direction

Do not add Docling or `docling-slim`.

Keep existing lightweight local and Mistral strategies. The registry remains
the extension boundary for future hosted OCR providers, a separately deployed
Docling API, or an MCP-backed conversion adapter. Provider additions must
return the existing `ExtractedDocument` contract and remain explicit settings
choices; no provider expansion is required for this tool.

Do not activate or redesign `RenderMode.CHUNKED`, `Chunk`,
`ExtractedDocument.blocks`, or the unused generic pipeline module as part of
this effort.

## Validation-First Delivery

Maintainers own the full validation suite. During implementation, add scenario
assertions before each behavior slice and run only the targeted scenarios plus
agent-owned static checks and focused smoke probes.

### Scenario 1: source disposition and vault paths

Extend the deterministic ingestion scenario or add a focused companion that
asserts:

- inbox scan imports a PDF and removes the inbox source
- a vault-relative PDF outside the inbox imports successfully and remains in
  place
- both output writes and the inbox deletion retain ingestion task/activity
  attribution
- traversal and symlink escape attempts are rejected before job creation

This scenario protects user data and crosses ingestion, path security, and
vault-state ownership, so it warrants integration coverage.

Decision events:

- `ingestion_source_resolved`: job id, vault, source kind, detected/persisted
  source location, source disposition
- `ingestion_source_cleanup`: job id, vault, source location, outcome

Do not log full credential-bearing URLs in event payloads.

### Scenario 2: remote content routing

Add a deterministic scenario with a controlled/mocked fetch response that
asserts:

- HTML bytes select HTML extraction and create markdown
- PDF bytes returned from a URL select configured PDF extraction and create
  markdown
- a misleading URL suffix does not override an authoritative MIME/signature
- unsupported binary content fails rather than passing through HTML extraction

Extend the live URL scenario only as a smoke check; do not make the durable
contract depend exclusively on external network availability.

Decision event:

- `ingestion_remote_classified`: job id, sanitized source, detected MIME,
  evidence category, effective URL identity without credentials/query/fragment

### Scenario 3: tool and Monty contract

Add a deterministic integration scenario that asserts:

- `content_import` appears in configured chat tools
- the same tool is directly bound in Monty
- singular and batch `submit` return structured queued job items
- `status` returns completed/failed state and vault-relative outputs
- cross-vault ids, invalid operations, invalid options, absolute paths, and
  oversized batches return stable structured failures
- the obsolete `import_content` helper is no longer advertised

Stable validation events:

- `content_import_submitted`: vault, accepted count, URL count, vault-file count,
  job ids
- `content_import_status_read`: vault, requested count, returned count

Avoid asserting on free-form agent prose or full tool descriptions.

## Implementation Order

### Phase 1: Lock the executable contracts

1. Add failing validation assertions for source preservation, remote PDF
   routing, and tool/Monty registration.
2. Finalize the tool operation schema, batch limit, structured metadata shape,
   and URL frontmatter expectation in those scenarios.
3. Add the typed source request and job-result serializers.

### Phase 2: Decouple ingestion source lifecycle

1. Persist and resolve vault-relative file sources.
2. Move cleanup out of storage and page-image special handling into one
   post-storage service step.
3. Adapt the inbox scanner to explicit consumptive disposition.
4. Preserve existing scan API and activity behavior.

### Phase 3: Route remote content by detected type

1. Preserve fetched bytes and classification metadata.
2. Select extraction strategies from `RawDocument.mime`.
3. Route remote PDFs through existing PDF text/OCR/page-image behavior.
4. Correct remote provenance rendering.
5. Preserve the single-URL API through the shared path.

### Phase 4: Add the configured tool

1. Implement shared batch submit/status behavior.
2. Add `core/tools/content_import.py` with structured failure handling.
3. Register the tool in `core/settings/settings.template.yaml`.
4. Add `docs/tools/content_import.md` and update current tool/ingestion
   architecture documentation.
5. Verify direct Monty binding.
6. Remove the obsolete authoring helper, registration, contract, and stub.

### Phase 5: Harden and prepare review

1. Run the targeted ingestion and tool scenarios; request maintainer full-suite
   results.
2. Run the production Python quality gate required by the coding standards.
3. Review logs for safe URL handling and useful failure context.
4. Confirm inbox cleanup, arbitrary vault-file preservation, URL security,
   scheduler processing, and Vault Activity attribution.
5. Align architecture and usage docs to the final current contract.

## Non-Goals

- Research discovery, candidate selection, or source scoring.
- Research manifests, library indexes, summaries, or progress tracking.
- Research-level deduplication, retry, or resumption policy.
- A batch table or research-specific database.
- Automatic browser fallback or inline browser-content handoff.
- Paywall bypass, credentials, or anti-bot circumvention.
- Bundled Docling or another heavyweight conversion stack.
- Office documents, JSON/API rendering, or new OCR providers in the initial
  delivery.
- Multiline Import UI or Vault Explorer Import/Convert in the initial delivery.
- Arbitrary host filesystem import through chat or Monty.

## Confirmed Contract Decisions

1. Batch limit: an editable setting with a default of 20 sources per call,
   large enough for practical agent batches while keeping tool payloads bounded.
2. Submission semantics: enqueue and return immediately; use
   `status` for observation.
3. Batch validation: validate the complete request before
   creating any jobs.
4. URL provenance frontmatter: retain `source` as the requested
   URL and add final URL only when it differs, without changing local-file
   provenance unnecessarily.
5. Placeholder compatibility: remove the unreleased,
   unimplemented `import_content` authoring helper when the configured tool is
   added.
6. Operational limits: batch sizes, timeouts, response-size limits, and similar
   deployment controls use editable settings with the recommended values as
   defaults. They are not unrestricted per-call tool arguments.

## Next Phase

Move to Feature Development and begin with the failing source-disposition
scenario. The first production change should remove cleanup responsibility from
`core/ingestion/storage.py`; the tool adapter comes only after source lifecycle
and remote routing contracts are safe.
