# Authoring Subsystem

The authoring subsystem handles discovery, parsing, and execution of both workflows and context templates. Both share the same file format and runtime: YAML frontmatter + one `python` block, executed in a Monty (sandboxed Python) environment.

## Primary code

- `core/authoring/template_discovery.py` — find and load authoring files from vaults and system
- `core/authoring/template_loader.py` — parse frontmatter and extract the Python block
- `core/authoring/engine.py` — run authoring files in the Monty sandbox
- `core/authoring/context_manager.py` — assemble chat context using context templates
- `core/authoring/registry.py` — register and resolve named authoring files
- `core/authoring/contracts.py` — shared types and result contracts

## File format

Every authoring file has:
- `run_type: workflow` or `run_type: context` in frontmatter
- Exactly one fenced `python` block containing the executable body

Workflows live in `AssistantMD/Authoring/` per vault (or `system/Authoring/` for system-level defaults). Context templates use the same location and format.

## Capability functions

The Monty sandbox exposes async host functions that authoring code calls to do real work:

| Function | Purpose |
| --- | --- |
| `generate` | Call the LLM |
| `call_tool` | Invoke a registered tool |
| `assemble_context` | Build chat context for a session |
| `read_cache` | Read a cached value |
| `pending_files` | List files awaiting processing |
| `parse_markdown` | Parse a markdown file |
| `finish` | Signal successful completion |

A `date` global is also injected, providing `date.today()`, `date.this_week()`, etc.

## Helpers

Helpers are the host-side implementations of capability functions — the bridge between sandboxed Monty code and the host runtime. Each helper is defined as an `AuthoringCapabilityDefinition` in `core/authoring/helpers/` and registered into an `AuthoringCapabilityRegistry` before sandbox execution.

The built-in catalog is assembled in `core/authoring/helper_catalog.py` via `create_builtin_registry()`. Each helper file exposes a `build_definition()` factory that binds the async host function (with access to LLM clients, tool registry, cache, vault paths) to the name the Monty sandbox calls it by.

This separation means the sandbox itself has no host imports — all side effects flow through the registered helper interface.

## Discovery and precedence

- `template_discovery.py` scans `AssistantMD/Authoring/` (one level deep) per vault.
- System templates in `system/Authoring/` provide defaults; vault files take precedence when names match.
- On first access, `ensure_vault_directories()` creates `AssistantMD/Authoring/` and `AssistantMD/Skills/` for each vault, seeding starter files from `core/authoring/seed_templates/`.

## Cache

The authoring subsystem has two SQLite-backed cache stores (`system/cache.db`), both managed by `core/authoring/cache.py`.

**Artifact cache** — general-purpose key-value store for authoring code. Authoring files write values with `call_tool` and read them back with `read_cache`. Keyed by `owner_id` + `artifact_ref`.

**Context cache** — stores the output of individual context template sections so expensive LLM calls aren't repeated across sessions when the result hasn't changed.

Both stores share the same set of cache modes:

| Mode | Validity |
| --- | --- |
| `session` | Valid for the current session only |
| `daily` | Valid until midnight of the day it was written |
| `weekly` | Valid until the start of the next week |
| `Nd` / `Nh` / `Nm` | Duration-based TTL (e.g. `24h`, `7d`, `30m`) |

Expired artifacts are purged on a schedule via `purge_expired_cache_artifacts`.

## Runtime interaction

- Runtime bootstrap creates the authoring registry and wires it to the scheduler.
- Scheduler sync (`setup_scheduler_jobs`) loads workflow definitions and reconciles APScheduler jobs.
- Chat sessions invoke the context manager, which runs the matching context template (or the default) to assemble the agent's starting context.
