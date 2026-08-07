# Content Import

`content_import` submits URLs or vault files to the durable ingestion pipeline
and reads the resulting job status. Imported content is written as vault
artifacts under the configured ingestion output path.

## Submit

Use `operation="submit"` with one source or a list of sources:

```text
content_import(
  operation="submit",
  sources=["https://example.org/report.pdf", "Research/local.pdf"]
)
```

Sources may be public HTTP/HTTPS URLs or vault-relative file paths. Vault files
are preserved after import. The call queues one durable ingestion job per source
and returns promptly; it does not wait for extraction to finish.

Optional `options`:

- `pdf_mode`: `markdown` or `page_images`
- `strategies`: ordered extraction strategy names
- `capture_ocr_images`: boolean
- `clean_html`: boolean

The maximum sources accepted per call is controlled by the editable
`content_import_max_batch_size` setting, which defaults to 20.

## Status

Use `operation="status"` with one job id or a list of job ids:

```text
content_import(operation="status", job_ids=[41, 42])
```

Status results include the job id, source, source kind, current state, output
paths, and any durable ingestion error. A caller can choose when to inspect
queued work; the tool does not define research progress or retry policy.

## Boundaries

- File paths are resolved inside the active vault. Absolute paths, traversal,
  symlink escapes, and virtual mounts are rejected.
- URL loading uses the configured ingestion transport, public-network policy,
  timeouts, and response-size limit.
- Initial remote conversion supports HTML and PDF responses.
- The tool does not search for sources, organize a library, summarize results,
  or track which sources a research effort still needs.
