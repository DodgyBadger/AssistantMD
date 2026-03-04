# Architecture Overview

AssistantMD is a single-user, markdown-first agent system. This page is the primary starting point for development docs.

## System Snapshot

```
FastAPI app (main.py, api/)
    ↓ lifespan bootstrap
Runtime context (core/runtime/)
    ↓ scheduler + loader + shared services
Workflow/Chat execution (core/workflow, core/llm, core/context)
    ↓ directives + tools + models
Vault files (data/) + system state (system/)
```

The web UI (`static/`) talks to API endpoints, and those endpoints route into the same runtime context and model/tool stack used by scheduled workflows.

## Core Runtime Loop

1. `main.py` resolves bootstrap roots and sets them before importing path-sensitive modules.
2. FastAPI lifespan builds `RuntimeConfig` and calls `bootstrap_runtime`.
3. Bootstrap validates configuration, initializes scheduler + workflow loader + ingestion services, then sets global runtime context.
4. Runtime reload syncs workflows into APScheduler jobs.
5. Triggers execute workflows (`run_workflow`) using lightweight `job_args`, directive processing, tool/model calls, and vault writes.

## Subsystems at a Glance

| Area | Responsibility | Primary code |
| --- | --- | --- |
| [Runtime](runtime.md) | Bootstrap, global context, path roots, config reload | `core/runtime/` |
| [API + UI](api-ui.md) | Endpoints, static UI, exception and lifecycle wiring | `api/`, `main.py`, `static/` |
| [Workflow Loader](workflow-loader.md) | Discover/parse workflow files and engine references | `core/workflow/` |
| [Scheduler](scheduler.md) | Persistent APScheduler jobs and synchronization | `core/scheduling/` |
| [Engines + Directives](engines-directives.md) | Execute workflow logic and parse `@directives` | `workflow_engines/`, `core/directives/` |
| [LLM + Tools](llm-tools.md) | Agent creation, tool loading, routing, model resolution | `core/llm/`, `core/tools/`, `core/directives/tools.py` |
| [Multimodal](multimodal.md) | Image inputs, chunking, prompt assembly, attachment policies | `core/chunking/`, `core/utils/image_inputs.py`, `core/tools/file_ops_safe.py` |
| [Context Manager](context-manager-subsystem.md) | Context-template execution | `core/context/` |
| [Settings + Secrets](settings-secrets.md) | Typed config store and YAML-backed secrets store | `core/settings/` |
| [Ingestion Pipeline](ingestion-pipeline.md) | Import queue, extraction strategies, rendering/storage, worker execution | `core/ingestion/`, `api/services.py` |
| [Validation](validation.md) | End-to-end test scenarios and artifacts | `validation/` |


See [Extending AssistantMD](extending.md) for guidance on how to fork and add your own custom workflow engines, tools and directives.
