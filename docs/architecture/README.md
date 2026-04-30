# Architecture Overview

AssistantMD is a single-user, markdown-first agent system. This page is the primary starting point for development docs.

## System Snapshot

```
FastAPI app (main.py, api/)
    ↓ lifespan bootstrap
Runtime context (core/runtime/)
    ↓ scheduler + authoring loader + ingestion + shared services
Chat execution (core/chat/) + Authoring execution (core/authoring/)
    ↓ Monty sandbox + tools + models
Memory/history broker (core/memory/) + Chat store (core/chat/)
    ↓
Vault files (data/) + system state/databases (system/)
```

The web UI (`static/`) talks to API endpoints, and those endpoints route into the same runtime context and model/tool stack used by scheduled workflows.

## Core Runtime Loop

1. `main.py` resolves bootstrap roots and sets them before importing path-sensitive modules.
2. FastAPI lifespan builds `RuntimeConfig` and calls `bootstrap_runtime`.
3. Bootstrap seeds system authoring files, validates configuration, initializes scheduler + authoring loader + ingestion services, then sets global runtime context.
4. Runtime reload syncs discovered workflows into APScheduler jobs.
5. Chat requests flow through `core/chat/executor.py`, which composes model, tools, context-template capability, tool-output cache hooks, and canonical session persistence.
6. Workflow triggers execute via the authoring engine (`core/authoring/engine.py`), which runs user-authored Python in a Monty sandbox with host-provided capability functions and vault writes.

## Subsystems at a Glance

| Area | Responsibility | Primary code |
| --- | --- | --- |
| [Runtime](runtime.md) | Bootstrap, global context, path roots, config reload | `core/runtime/` |
| [API + UI](api-ui.md) | Endpoints, static UI, exception and lifecycle wiring | `api/`, `main.py`, `static/` |
| [Authoring](authoring-engine.md) | Discover/parse/execute workflows and context templates in the Monty sandbox, including script helpers | `core/authoring/` |
| [Scheduler](scheduler.md) | Persistent APScheduler jobs and synchronization | `core/scheduling/` |
| [Chat Sessions](chat-sessions.md) | SQLite session store and markdown transcript rendering | `core/chat/` |
| [Memory](memory.md) | Shared conversation-history broker for tool adapters and authoring helpers | `core/memory/` |
| [LLM + Tools](llm-tools.md) | Agent creation, settings-backed tool binding, capability composition, model resolution | `core/llm/`, `core/tools/` |
| [Multimodal](multimodal.md) | Image inputs, chunking, prompt assembly, attachment policies | `core/chunking/`, `core/utils/image_inputs.py`, `core/tools/file_ops_safe.py` |
| [Settings + Secrets](settings-secrets.md) | Typed config store and YAML-backed secrets store | `core/settings/` |
| [Ingestion Pipeline](ingestion-pipeline.md) | Import queue, extraction strategies, rendering/storage, worker execution | `core/ingestion/`, `api/services.py` |
| [Validation](validation.md) | End-to-end test scenarios and artifacts | `validation/` |
