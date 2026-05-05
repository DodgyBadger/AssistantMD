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
- Service-layer orchestration for runtime operations.
- Static single-page UI hosting.

## Request routing model

1. UI calls API endpoint.
2. Endpoint validates payload and calls service function.
3. Service function uses runtime context (`get_runtime_context()`), settings, and domain modules.
4. Response returns serialized system/domain results.

## Operational notes

- Endpoint logic is intentionally thin; most behavior should live in services/core modules.
- Config and secret updates trigger reload through runtime reload service.
- Ingestion and workflow manual runs are surfaced via API services.
- Chat and workflow execution endpoints register process-local execution tasks through runtime services.
- `/api/tasks`, `/api/tasks/{task_id}`, and `/api/tasks/{task_id}/cancel` expose task snapshots and cancellation.
- `/api/chat/sessions/{session_id}/active-task` and `/api/chat/sessions/{session_id}/cancel` expose chat-session-scoped task lookup and cancellation.
- `/api/chat/sessions/{session_id}/compaction-status` and `/api/chat/sessions/{session_id}/compact` expose chat history compaction status and execution.
- Interactive API docs are available at `/docs` (Swagger UI) and `/openapi.json` (OpenAPI schema).
- The OpenAPI schema is the source of truth for endpoint shapes.
- Security: no built-in auth/TLS by default; if deployed remotely, place behind network/auth controls.
