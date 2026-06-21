# API + UI Subsystem

The API + UI layer exposes runtime features to users and keeps web interactions aligned with runtime services.

## Primary code

- `main.py`
- `api/endpoints.py`
- `api/services.py`
- `api/models.py`
- `static/`

## Responsibilities

- FastAPI lifespan startup/shutdown around runtime bootstrap.
- REST endpoints for chat, workflows, config, ingestion, and metadata.
- REST endpoints for process-local execution task visibility and cancellation.
- REST endpoints for vault mutation activity and manual vault-state cleanup.
- Service-layer orchestration for runtime operations.
- Static single-page UI hosting.

## Request routing model

1. UI calls API endpoint.
2. Endpoint validates payload and calls service function.
3. Service function uses runtime context (`get_runtime_context()`), settings, and domain modules.
4. Response returns serialized system/domain results.

## Operational notes

- Endpoint logic is intentionally thin; most behavior should live in services/core modules.
- Error responses keep the stable top-level `success`, `error`, and `message` fields. `details` includes an agent-safe recovery envelope with `status`, `error_type`, `phase`, `failure_kind`, `retryable`, `suggested_action`, and relevant ids when available. Unexpected errors keep tracebacks in server logs and debug responses only.
- Config and secret updates trigger reload through runtime reload service.
- Ingestion and workflow manual runs are surfaced via API services.
- The Dashboard tab hosts vault overview, workflow controls, import controls, and vault activity.
- The System tab hosts app settings, provider/model configuration, secrets, logs, cleanup, system jobs, system authoring refresh, and database migration status/manual fallback.
- Chat and workflow execution endpoints register process-local execution tasks through runtime services.
- `/api/tasks`, `/api/tasks/{task_id}`, and `/api/tasks/{task_id}/cancel` expose task snapshots and cancellation.
- `/api/chat/tasks` is the canonical chat execution entrypoint. It creates a task-owned streaming chat run; clients observe live events through `/api/chat/tasks/{task_id}/events`, task status through `/api/tasks/{task_id}`, or persisted history through session detail endpoints.
- `/api/chat/tasks/{task_id}/events` returns `410 ChatTaskEventsExpired` when a known terminal chat task still exists but its process-local event buffer has been pruned.
- Multipart chat image uploads enforce configured image count, per-image bytes, and total image bytes at the API boundary while reading upload streams. Oversized uploads return `413` before task creation.
- `/api/vaults/{vault_name}/task-mutations` exposes grouped task file mutation activity for the Dashboard tab.
- `/api/vault-state/snapshots/{snapshot_id}/content` serves retained vault-state snapshot files inline after resolving them under the managed snapshot root.
- `/api/vault-state/cleanup` deletes expired vault-state mutation rows and retained task snapshot artifacts.
- `/api/system/migrations/status` and `/api/system/migrations/run` expose registered system database migration status and manual execution.
- `/api/chat/sessions/{session_id}/active-task` and `/api/chat/sessions/{session_id}/cancel` expose chat-session-scoped task lookup and cancellation.
- `/api/chat/sessions/{session_id}/compaction-status` and `/api/chat/sessions/{session_id}/compact` expose chat history compaction status and execution.
- Interactive API docs are available at `/docs` (Swagger UI) and `/openapi.json` (OpenAPI schema).
- The OpenAPI schema is the source of truth for endpoint shapes.
- Security: no built-in auth/TLS by default; if deployed remotely, place behind network/auth controls.
