# Context Compiler Requirements and Phases

## Requirements (brief)
- Preserve full chat transcript in markdown as today.
- Add opt-in “Endless” mode using a context compiler instead of append-all history.
- Context compiler consumes a named template (path/name provided by UI/directive).
- Template resolution: vault `AssistantMD/ContextTemplates/` first, then `system/ContextTemplates/`; record source/hash.
- Produce curated working view driven by templates; fail open to a normal chat run if compilation fails.
- Persist compiled views to SQLite in `system/` with observability (template metadata, included sections, budget stats).
- Keep compiler reusable for future workflow directive (`@context-helper templatename`).
- Use the same model as the chat selection or workflow `@model`; route through existing `core/llm` agent creation; record model alias used.

## Phases

1) Templates & Loader (done/ready)
- Default template shipped in `system/ContextTemplates/`; resolve vault → system with hash/source metadata.
- Templates remain markdown prompts with optional JSON contract block; missing placeholders render empty.

2) Compiler Core (partially done)
- Inputs assembled in chat layer and passed as a `context_payload`; currently simplified to the latest user input and recent message history.
- Compiler originally enforced JSON-only via `output_type=Dict[str, Any]` using template instructions + system note; this is temporarily disabled while we debug provider differences (OpenAI Responses vs. others) and output validation.
- Drop-order/token budgeting deferred; add sections-included/budget observability if/when we add truncation logic.
- Fail-open: if compilation fails, proceed with normal chat prompt (no compiled preamble).

3) SQLite Store (done)
- `system/context.db` with `sessions` and `context_summaries`; DAL inserts template metadata, model alias, raw/parsed output, compiled prompt, input payload.

4) Chat Integration (“Endless” Mode) (done/usable)
- UI toggle + template dropdown wired; API resolves template and invokes compiler; persists summary; falls back to normal chat on errors.
- Markdown transcript unchanged; template source/hash recorded; history slicing aligned via SessionManager helpers (last N non-tool messages; tools via filtered recent slice).
- Compiled summary is currently injected into chat instructions (endless mode) rather than the prompt; we’re experimenting with placement (instructions vs. system vs. history) to improve reliability across providers.

5) Tests & Observability (pending/partial)
- Need unit coverage for template resolution and compiler fallback; add integration scenarios for Endless mode; add tracing for history lengths/outputs. Drop-order tests only if truncation is added later.

6) Workflow Directive (later)
- Add `@context-helper <template>` directive to workflow steps reusing the compiler; respect fail-open semantics.

### Additional Implementation Notes
- Start simple: use template instructions directly; optional YAML/JSON schema in the template is advisory only (no dynamic Pydantic model/validation). Compiler now enforces JSON-only via `output_type=Dict[str, Any]` but still stores raw output for observability.
- Drop-order/token budgeting is deferred; templates can self-limit (e.g., “3-4 sentences”). Add truncation rules later if needed.
- Reflections: data lives in compiler state; template exposes it via a placeholder/key. Decide generation triggers (e.g., every N turns or on tool failures).
- Progress so far:
  - UI: “Endless” mode and template dropdown added; templates listed via `/api/context/templates` (vault + system).
  - Settings: added `context_compiler_recent_turns`, `context_compiler_recent_tool_results`.
  - Compiler: uses template + system note. `output_type` was enforcing JSON-only; currently disabled for troubleshooting provider differences (OpenAI Responses vs. Anthropic). Still persists raw/parsed output, input payload, compiled prompt to `context_compiler.db`.
  - History handling: SessionManager now exposes `get_recent`/`get_recent_matching`; endless mode feeds the same last-N non-tool messages into both compiler and chat agent; tool calls gathered via filtered recent slice; removed `use_conversation_history`.
  - Chat integration: Endless mode compiles context, and we’re iterating on where to place the compiled summary (instructions vs. system vs. history). Transcript unchanged; prior compiled summary is no longer stuffed into a fixed payload (payload is now minimal/latest input).
  - Storage: `context_compiler.db` with sessions/context_summaries; observability fields include compiled_prompt and input_payload.
  - Gaps: recent-turns alignment fixed (shared slicing, no dict→message hop). Ongoing: reliable structured output across providers; placement of compiled summary; deciding final shape for system/user prompts to avoid model confusion.
