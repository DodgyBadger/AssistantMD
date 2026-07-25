# Vault Explorer Upload Implementation Plan

## Status

Implemented and hardened. Focused validation passes via
`integration/core/vault_explorer_upload`; maintainer full-suite and browser
review remain pending.

## Goal

Add a Vault Explorer upload operation so a user can place local documents,
including PDFs, into the selected vault without requiring host filesystem
access. Files uploaded to `AssistantMD/Import/` remain compatible with the
existing ingestion flow for Markdown conversion.

## User-Visible Contract

- The Vault Explorer header exposes an Upload action alongside create and
  refresh controls.
- The browser file chooser accepts one or more files.
- Before transfer, the Explorer shows an editable vault-relative destination
  directory. It defaults to the active workspace when the workspace filter is
  active and otherwise defaults to the vault root.
- Each file retains its local basename. The UI previews the resulting
  vault-relative paths.
- Existing destination files are rejected; upload never silently overwrites
  vault content.
- Successful uploads refresh and reveal the uploaded files. Per-file failures
  remain visible without hiding files that uploaded successfully.
- Uploading to `AssistantMD/Import/` stages supported documents for the existing
  Import Files flow. Upload does not duplicate PDF extraction or ingestion
  strategy selection.

## Invariants

- Every persisted upload is resolved inside the selected vault and written
  through the shared vault mutation recorder.
- Multipart input is bounded while being read. The API does not trust browser
  filenames as destination paths.
- Destination validation runs before multipart parsing and again before the
  recorded write. Absolute paths, traversal/dot components, control
  characters, overlong paths, and symlink-resolved vault escapes are rejected.
- Requests contain exactly one multipart file part; unrelated fields or file
  parts are rejected.
- The per-file boundary comes from `vault_upload_max_mb_per_file`; `0` disables
  uploads and the default is 100 MB.
- A failed upload cannot leave a partially written destination file.
- Binary files are not routed through the text-file mutation API.
- Upload and ingestion remain separate operations with separate activity
  attribution.

## Affected Areas

- `static/js/vault-path-picker.js`
  - header upload control, file selection, destination form, upload requests,
    result reporting, and tree refresh/reveal.
- `static/app.css`
  - themed upload form, file list, responsive layout, and status styling.
- `api/endpoints.py`
  - bounded multipart upload endpoint.
- `api/services.py`
  - vault/path validation and recorded binary-file creation.
- `api/models.py`
  - stable upload response contract if a response model is appropriate.
- `core/settings/__init__.py` and `core/settings/settings.template.yaml`
  - typed upload-limit accessors and the editable default.
- `docs/architecture/api-ui.md`
  - current upload API boundary and size/failure behavior.

## Validation Target

- Add a focused integration scenario proving:
  - binary bytes are preserved;
  - the destination is represented in vault mutation history;
  - an existing destination is rejected without replacement;
  - oversized input is rejected without creating a file;
  - traversal/out-of-vault destinations are rejected.
- Run local syntax, formatting, and narrow API smoke checks.
- Request maintainer execution of the full validation suite.
- Manually verify the Explorer flow in light/dark themes at desktop and narrow
  viewport widths.

## Implementation Steps

1. Add a service helper that validates a vault-relative destination and calls
   the existing recorded binary write operation with create-only semantics.
2. Add a multipart endpoint that reads one upload in bounded chunks and invokes
   the service helper only after the complete payload passes validation.
3. Add the Explorer header control and a themed upload form with editable
   destination directory and path previews.
4. Upload selected files individually so one failure does not create ambiguous
   batch transaction semantics; report each result explicitly.
5. Refresh the Explorer once after the batch and reveal an uploaded path.
6. Add focused scenario coverage, update the API/UI architecture contract, and
   complete a refactor/hardening pass.

## Hardening Review

- The create-only binary mutation boundary now uses exclusive file creation and
  removes a partially written destination when the write fails.
- A focused regression assertion simulates an interrupted binary write and
  confirms that the API reports failure without leaving the destination behind.
- The final create remains protected by the shared per-path mutation lock, and
  an external destination race is translated to the existing `file_exists`
  mutation contract.

## Next Phase

Maintainer browser review and full-suite validation, followed by commit and
merge-readiness review.
