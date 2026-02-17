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
