# Context Compiler Requirements and Phases

## Requirements (brief)
- Preserve full chat transcript in markdown as today.
- Add opt-in “Endless” mode using a context compiler instead of append-all history.
- Context compiler consumes a named template (path/name provided by UI/directive).
- Template resolution: vault `AssistantMD/ContextTemplates/` first, then `system/ContextTemplates/`; record source/hash.
- Produce curated working view under a token budget with clear drop order; fail open to append-all on errors.
- Persist compiled views to SQLite in `system/` with observability (template metadata, included sections, budget stats).
- Keep compiler reusable for future workflow directive (`@context-helper templatename`).
- Use the same model as the chat selection or workflow `@model`; route through existing `core/llm` agent creation; record model alias used.

## Phases

1) Templates & Loader
- Ship default template(s) in `system/ContextTemplates/`.
- Load templates by name with vault→system resolution and hash/version metadata.
- Templates are markdown instructions plus an explicit JSON contract in a fenced block. Keep placeholders/keys simple (constraints, plan, recent turns/tool outputs, reflections, latest input).
- Lenient rendering: missing placeholders render empty; record template hash/source/name.

2) Compiler Core
- Implement state inputs (constraints/goals, plan/subtasks, recent turns/tool outputs, reflections, latest input).
- Apply drop-order/budget logic; emit rendered working view text plus observability (sections included/dropped, token estimates).
- Return structured summary JSON for storage and sending to the model; hard fail triggers append-all fallback.

3) SQLite Store
- Create `system/context.db` with `sessions` and `context_summaries` tables.
- Data-access layer for inserting session metadata and per-turn summaries (template source/name/hash, budget_used, sections_included, rendered view).
- Migration/bootstrap helper to create the DB if missing.

4) Chat Integration (“Endless” Mode)
- Add chat mode toggle and template dropdown (UI passes template name).
- In chat path, invoke compiler; on success send compiled view to model and persist summary; on error fall back to existing behavior.
- Keep markdown transcript unchanged; log template source/hash in activity.

5) Tests & Observability
- Unit tests (ephemeral bash-driven) for template resolution, compile drop-order/budget behavior, and fallback path.
- Integration coverage via validation framework: add scenarios exercising chat “Endless” mode with default template (and later workflow directive).
- Add minimal tracing/log lines for compiled sections and budget use.

6) Workflow Directive (later)
- Add `@context-helper <template>` directive to workflow steps.
- Reuse compiler; inject curated preamble/helper file; respect fail-open semantics.

### Additional Implementation Notes
- Start simple: use template instructions directly; optional YAML/JSON schema in the template is advisory only (no dynamic Pydantic model/validation for now). Best-effort JSON parsing; store raw output if parsing fails.
- Define a default drop-order/budget policy (e.g., system/instructions > constraints/goals > plan/subtask > latest input + last N turns/tool outputs > reflections) and within-section truncation rules; record which path was used (model compression vs. deterministic truncation).
- Reflections: data lives in compiler state; template exposes it via a placeholder/key. Decide generation triggers (e.g., every N turns or on tool failures).
- Progress so far:
  - UI: “Endless” mode and template dropdown added; templates listed via new `/api/context/templates` (vault + system).
  - Settings: added `context_compiler_recent_turns`, `context_compiler_recent_tool_results`, `context_compiler_max_tokens`.
  - Compiler: simple best-effort summary using template + shared system note; persists raw/parsed output, input payload, compiled prompt to `context_compiler.db`; tool results captured from history when available.
  - Chat integration: Endless mode compiles context, prepends compiled summary to agent prompt, and uses last N turns as message_history; conversation history always stored; prior compiled summary seeds topic/constraints/plan/reflections/tool_results.
  - Storage: `context_compiler.db` with sessions/context_summaries; observability fields include compiled_prompt and input_payload.
- Gap to resolve:
  - Recent turns to compiler: despite building recent_turns payload and message_history, only one turn seems to reach the compiler. Need to audit SessionManager messages, pydantic_ai ModelMessage construction, and ensure both compiler and agent receive the intended last N turns (default 3). Might need explicit logging of message_history length and contents before compiler/agent calls.
