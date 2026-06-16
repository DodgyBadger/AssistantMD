# Architecture Overview

AssistantMD is a single-user, markdown-first agent system. This page is the primary starting point for development docs.

Architecture decision records live under `docs/adr/`.
They explain why durable system shapes were chosen; this architecture section
remains the source of truth for how the system works now.

## System Snapshot

```
FastAPI app (main.py, api/)
    ↓ lifespan bootstrap
Runtime context (core/runtime/)
    ↓ scheduler + authoring loader + ingestion + execution tasks + vault state + shared services
Chat execution (core/chat/) + Authoring execution (core/authoring/)
    ↓ Monty sandbox + tools + models
Session summaries (core/memory/) + Chat/history services (core/chat/)
    ↓
Vault files (data/) + system state/databases/snapshots (system/)
```

The web UI (`static/`) talks to API endpoints, and those endpoints route into the same runtime context and model/tool stack used by scheduled workflows.

## Core Runtime Loop

1. `main.py` resolves bootstrap roots and sets them before importing path-sensitive modules.
2. FastAPI lifespan builds `RuntimeConfig` and calls `bootstrap_runtime`.
3. Bootstrap seeds system authoring files, validates configuration, initializes scheduler + authoring loader + ingestion services + execution task coordination, then sets global runtime context.
4. Runtime reload syncs discovered workflows into APScheduler jobs.
5. Chat requests flow through `core/chat/executor.py`, which composes model, tools, context-template capability, tool-output cache hooks, execution task tracking, and canonical session persistence.
6. Workflow triggers execute through the workflow governor and authoring engine, which enforce vault-level execution lanes before running user-authored Python in a Monty sandbox with host-provided capability functions and vault writes.

## Subsystems at a Glance

| Area | Responsibility | Primary code |
| --- | --- | --- |
| [Runtime](runtime.md) | Bootstrap, global context, path roots, config reload | `core/runtime/` |
| [API + UI](api-ui.md) | Endpoints, static UI, exception and lifecycle wiring | `api/`, `main.py`, `static/` |
| [Execution Tasks](execution-tasks.md) | Process-local task snapshots, cancellation, and task lifecycle events | `core/runtime/execution_tasks.py`, `core/runtime/workflow_governor.py` |
| [Vault State](vault-state.md) | Vault manifest, change feed, task mutation audit, snapshots, and rollback | `core/vault_state/` |
| [Authoring](authoring-engine.md) | Discover/parse/execute workflows and context templates in the Monty sandbox, including script helpers | `core/authoring/` |
| [Scheduler](scheduler.md) | Persistent APScheduler jobs and synchronization | `core/scheduling/` |
| [Chat Sessions](chat-sessions.md) | SQLite session store and markdown transcript rendering | `core/chat/` |
| [Session Summaries](session-summaries.md) | Derived chat-session summary storage, indexing, and retrieval | `core/memory/`, `core/chat/history_service.py` |
| [Goals](goals.md) | Lightweight durable goal state, checkpoints, source provenance, and goal-related activity | `core/goals/`, `core/tools/goal_ops.py` |
| [LLM + Tools](llm-tools.md) | Agent creation, settings-backed tool binding, capability composition, model resolution | `core/llm/`, `core/tools/` |
| [Multimodal](multimodal.md) | Image inputs, chunking, prompt assembly, attachment policies | `core/chunking/`, `core/utils/image_inputs.py`, `core/tools/file_ops_safe.py` |
| [Settings + Secrets](settings-secrets.md) | Typed config store and YAML-backed secrets store | `core/settings/` |
| [Ingestion Pipeline](ingestion-pipeline.md) | Import queue, extraction strategies, rendering/storage, worker execution | `core/ingestion/`, `api/services.py` |
| [Validation](validation.md) | End-to-end test scenarios and artifacts | `validation/` |
