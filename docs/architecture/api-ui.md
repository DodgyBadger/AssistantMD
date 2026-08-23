# API + UI Subsystem

The API + UI layer exposes runtime features to users and keeps web interactions aligned with runtime services.

## Primary code

- `main.py`
- `api/endpoints.py`
- `api/services/` — domain service modules with stable re-exports from
  `api.services`
- `api/models.py`
- `static/`
- `static/app.js` — chat task submission, event-stream reconnect, and canonical reload
- `static/js/chat-rendering.js` — message, tool-row, and tool-detail rendering
- `static/js/deferred-reviews.js` — inline tool-review cards and submission
- `static/js/file-references.js` — chat path resolution and file view
- `static/js/vault-path-picker.js` — shared Vault Explorer tree and path actions
- `static/js/vault-activity.js` — activity detail and rollback UI

## Responsibilities

- FastAPI lifespan startup/shutdown around runtime bootstrap.
- REST endpoints for chat, workflows, config, ingestion, and metadata.
- REST endpoints for process-local execution task visibility and cancellation.
- REST endpoints for vault mutation activity and manual vault-state cleanup.
- REST endpoints for Vault Explorer navigation, text editing, path mutations,
  file revisions, and activity rollback.
- Durable chat-mode and deferred-review interactions over the normal chat task
  lifecycle.
- Service-layer orchestration for runtime operations.
- Static single-page UI hosting.

API service ownership is split by domain: chat sessions, configuration,
deferred reviews, execution tasks, ingestion, maintenance, system status,
activity, vault files, and workflows. `api.services` remains the stable import
surface used by endpoints and validation.

## Request routing model

1. UI calls API endpoint.
2. Endpoint validates payload and calls service function.
3. Service function uses runtime context (`get_runtime_context()`), settings, and domain modules.
4. Response returns serialized system/domain results.

## Operational notes

- First-party frontend code accesses browser persistence through
  `static/js/browser-storage.js`. The boundary catches storage access failures
  and uses page-lifetime memory when local storage is unavailable, including in
  opaque-origin sandboxed iframes. Browser storage is never required for UI
  initialization.
- Endpoint logic is intentionally thin; most behavior should live in services/core modules.
- Error responses keep the stable top-level `success`, `error`, and `message` fields. `details` includes an agent-safe recovery envelope with `status`, `error_type`, `phase`, `failure_kind`, `retryable`, `suggested_action`, and relevant ids when available. Unexpected errors keep tracebacks in server logs and debug responses only.
- Config and secret updates trigger reload through runtime reload service.
- Ingestion and workflow manual runs are surfaced via API services.
- The Dashboard tab hosts vault overview, workflow controls, import controls, and vault activity.
- The Import section reads durable ingestion status from `/api/import/jobs`,
  cancels queued work through `/api/import/jobs/{job_id}/cancel`, and requests a
  scheduler-owned worker run through `/api/import/run-now`.
- The System tab hosts app settings, provider/model configuration, secrets, logs, cleanup, system jobs, system authoring refresh, and database migration status/manual fallback.
- OpenAI OAuth controls live in the System provider configuration surface and call the provider OAuth endpoints; API responses expose only sanitized OAuth status, not token material.
- Chat and workflow execution endpoints register process-local execution tasks through runtime services.
- `/api/tasks`, `/api/tasks/{task_id}`, and `/api/tasks/{task_id}/cancel` expose task snapshots and cancellation.
- `/api/chat/tasks` is the canonical chat execution entrypoint. It creates a task-owned streaming chat run; clients observe live events through `/api/chat/tasks/{task_id}/events`, task status through `/api/tasks/{task_id}`, or persisted history through session detail endpoints.
- `/api/chat/tasks/{task_id}/events` returns `410 ChatTaskEventsExpired` when a known terminal chat task still exists but its process-local event buffer has been pruned.
- Chat event subscribers reconnect from the last observed sequence. Session
  reload attaches to the session's active task; an expired replay cursor clears
  provisional output, lets the task finish in the background, and reloads
  canonical persisted history.
- A recovery attempt may reset the provisional assistant response. Recovery
  that requires rollback ends the source stream with `chat_retry_redirect`; the
  browser follows the replacement task and resets its event sequence.
- Tool rows are created from `tool_call_started` and finalized from
  `tool_call_finished`. Their icon reflects `running`, `completed`, `failed`, or
  `interrupted`; elapsed time and the status label live in the detail modal.
- `GET /api/chat/sessions/{session_id}/tools/{tool_call_id}?vault_name=...`
  returns the session-owned persisted tool detail. The UI keeps inline previews
  bounded, loads full stored arguments and normal-sized results when the modal
  opens, and copies that full content rather than the truncated preview.
- Chat sessions persist `normal` or `inline_edit` mode through
  `/api/chat/sessions/{session_id}/mode`. In inline edit mode, a `review_required`
  task event renders a structured `file_write` review card inside the assistant
  turn.
- Deferred review data is read and submitted through
  `/api/vaults/{vault_name}/chat/{session_id}/deferred-reviews/...`. The frontend
  submits structured per-call decisions and editable argument values; backend
  services construct Pydantic AI approval/denial results and resume chat.
- Multipart chat image uploads enforce configured image count, per-image bytes, and total image bytes at the API boundary while reading upload streams. Oversized uploads return `413` before task creation.
- Vault Explorer file uploads use
  `POST /api/vaults/{vault_name}/files/upload?path=<vault-relative-path>`.
  The endpoint accepts one multipart file per request, enforces
  `vault_upload_max_mb_per_file` while reading, rejects existing destinations,
  and records the binary-safe create through the shared vault mutation history.
  A value of `0` disables Explorer uploads. The Explorer sends multi-file
  selections as independent requests so partial batch results remain explicit.
- `/api/vaults/{vault_name}/activity` exposes durable attributed vault activity for the Dashboard tab.
- `/api/vaults/{vault_name}/activity/{activity_id}/rollback` previews and applies
  all-or-nothing activity rollback.
- `/api/vault-state/snapshots/{snapshot_id}/content` serves retained vault-state snapshot files inline after resolving them under the managed snapshot root.
- `/api/vaults/{vault_name}/files/revisions` exposes retained exact-path revisions for the Vault Explorer file history view.
- `/api/vaults/{vault_name}/files/revisions/{snapshot_id}/restore` restores a retained revision under optimistic concurrency and records a new Explorer mutation.
- `/api/vault-state/cleanup` deletes expired vault activity, mutation, and retained task snapshot artifacts.
- `/api/system/migrations/status` and `/api/system/migrations/run` expose registered system database migration status and manual execution.
- `/api/system/activity-log` returns newest-first parsed System Activity entries
  with opaque cursor pagination and server-side time, level, tag, and text
  filters across retained daily segments. It includes the earliest retained
  timestamp and available filter values. `/api/system/activity-log/export`
  streams the retained raw JSONL history in chronological order.
- `/api/chat/sessions/{session_id}/active-task` and `/api/chat/sessions/{session_id}/cancel` expose chat-session-scoped task lookup and cancellation.
- `/api/chat/sessions/{session_id}/compaction-status` and `/api/chat/sessions/{session_id}/compact` expose chat history compaction status and execution.
- Interactive API docs are available at `/docs` (Swagger UI) and `/openapi.json` (OpenAPI schema).
- The OpenAPI schema is the source of truth for endpoint shapes.
- Security: no built-in auth/TLS by default; if deployed remotely, place behind network/auth controls.

The System Activity viewer submits filters to the server, loads older pages on
demand, and can export the retained raw history. Superseded searches are
cancelled in the browser so slower responses cannot replace newer results.

## Inline Review UI

The review card represents deferred `file_write` calls, not a second edit
protocol. Each row exposes the operation and target, editable fields permitted
by the backend, and approve or deny decisions. Submitting the card locks it and
starts the continuation task returned by the review API. A pending review loaded
with session detail locks ordinary prompt submission so a later message cannot
overtake the paused tool call.

The active review expands to the available assistant-message width so editing is
comfortable on desktop while remaining responsive on mobile. Resolved outcomes
are represented by canonical chat tool history; only an unresolved card is
reconstructed after session reload.

## Unified Vault Explorer

The Vault Explorer is one modal surface used from the chat toolbar, workspace
selection, resolved file/folder links in rendered messages, and activity
snapshots. It always permits navigation across the active vault even when opened
at a specific file or directory.

The shared tree supports folder expansion and per-path actions for adding a
reference to the prompt, copying a vault-relative path, setting the workspace,
creating files/folders, moving or renaming paths, and deleting paths. Direct
mutations call `/api/vaults/{vault_name}/paths/mutate` and execute as attributed
Explorer activities. While a chat task or deferred review is active, the modal
remains browsable but all mutation, editor, workspace, and prompt-insertion
actions are read-only to avoid stale concurrent edits.

Selecting a UTF-8 text file opens the file surface. Markdown files begin in a
rendered preview with soft line breaks, sanitized inline HTML, and collapsed YAML
frontmatter properties; edit mode exposes raw source. Other UTF-8 text files are
editable as plain text. Known binary media types, files with binary control
bytes, invalid UTF-8, and oversized files remain visible in the tree but are
rejected by the file API rather than opened in the editor. Saves include the
opened content hash for optimistic concurrency.

The same file surface lists retained exact-path revisions and can restore one as
a new Explorer activity. Activity snapshots open this revision view instead of
using a separate snapshot viewer. Revision history is path-based and does not
follow moves or renames.

Rendered assistant text is scanned for conservative vault path candidates, then
resolved by `/api/vaults/{vault_name}/file-refs/resolve` before becoming live
links. Explicit `@path` references and paths inside backticks are supported;
workspace-root matches take precedence for relative candidates. Unresolved paths
remain ordinary text, which avoids opening nonexistent proposed files.
