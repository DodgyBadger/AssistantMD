# Architecture Overview

AssistantMD is a single-user, markdown-first agent system. This page is the primary starting point for development docs.

## System Snapshot

```
FastAPI app (main.py, api/)
    ↓ lifespan bootstrap
Runtime context (core/runtime/)
    ↓ scheduler + authoring loader + shared services
Authoring execution (core/authoring/) + Chat (core/llm/)
    ↓ Monty sandbox + tools + models
Vault files (data/) + system state (system/)
```

The web UI (`static/`) talks to API endpoints, and those endpoints route into the same runtime context and model/tool stack used by scheduled workflows.

## Core Runtime Loop

1. `main.py` resolves bootstrap roots and sets them before importing path-sensitive modules.
2. FastAPI lifespan builds `RuntimeConfig` and calls `bootstrap_runtime`.
3. Bootstrap validates configuration, initializes scheduler + authoring loader + ingestion services, then sets global runtime context.
4. Runtime reload syncs workflows into APScheduler jobs.
5. Triggers execute workflows via the authoring engine (`core/authoring/engine.py`), which runs user-authored Python in a Monty sandbox with host-provided capability functions and vault writes.

## Subsystems at a Glance

| Area | Responsibility | Primary code |
| --- | --- | --- |
| [Runtime](runtime.md) | Bootstrap, global context, path roots, config reload | `core/runtime/` |
| [API + UI](api-ui.md) | Endpoints, static UI, exception and lifecycle wiring | `api/`, `main.py`, `static/` |
| [Authoring](authoring-engine.md) | Discover/parse/execute workflows and context templates in the Monty sandbox | `core/authoring/` |
| [Scheduler](scheduler.md) | Persistent APScheduler jobs and synchronization | `core/scheduling/` |
| [Chat Sessions](chat-sessions.md) | SQLite session store and markdown transcript rendering | `core/chat/` |
| [LLM + Tools](llm-tools.md) | Agent creation, tool loading, routing, model resolution | `core/llm/`, `core/tools/` |
| [Multimodal](multimodal.md) | Image inputs, chunking, prompt assembly, attachment policies | `core/chunking/`, `core/utils/image_inputs.py`, `core/tools/file_ops_safe.py` |
| [Settings + Secrets](settings-secrets.md) | Typed config store and YAML-backed secrets store | `core/settings/` |
| [Ingestion Pipeline](ingestion-pipeline.md) | Import queue, extraction strategies, rendering/storage, worker execution | `core/ingestion/`, `api/services.py` |
| [Validation](validation.md) | End-to-end test scenarios and artifacts | `validation/` |
