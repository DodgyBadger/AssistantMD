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

4) Chat Integration (“Endless” Mode) (refactored to history_processor)
- UI toggle + template dropdown wired; endless mode attaches a history_processor built via `build_compiling_history_processor`.
- Compiler now runs stateless (no message_history), prompt = compiler prompt + template + rendered recent turns + latest input; minimal compiler instruction stays in agent.instructions; output treated as natural language.
- History processor injects one system message (“Context summary (compiled): …”) before the recent non-tool turns and persists the compiled view; chat executor is clean again (no inline compilation/persistence).
- Markdown transcript unchanged; template source/hash recorded.
- New direction: simplify by using Pydantic AI `history_processors` on the chat agent. The processor will (per user turn) slice/reshape history, run the compiler, and return the curated message stack (e.g., prepend system message with compiled summary). Transcript storage stays untouched; avoid recursion by keeping the compiler’s agent processor-free and run it once per turn, caching the result for persistence. See https://ai.pydantic.dev/message-history/#processing-message-history

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
- Compiler: stateless; template + rendered recent turns + latest input form the prompt; minimal compiler instruction in agent.instructions; output is natural language (no JSON parse). Persistence happens in the history processor.
- History handling: history_processor injects compiled summary (system message) + recent non-tool turns. Tool calls/results are currently dropped; if we need tool context, we must include paired tool messages or render tool summaries to avoid the “tool call/return pairing” warning.
- Chat integration: chat executor just sets instructions, attaches the history processor in endless mode, and runs the chat agent; no inline compilation or persistence.
- Storage: `context_compiler.db` with sessions/context_summaries; observability includes raw output and input payload.
- Gaps: tool history gap (see above), provider placement/rules still to be validated, integration tests pending.
- Future considerations:
  - Cache inside the history processor (keyed on rendered history + latest input) to avoid re-running the compiler on tool retries or unchanged slices.
  - Reactive guard: only compile when needed (e.g., when history/token estimate exceeds a threshold) or as a retry path after provider errors, to avoid unnecessary summarization on short turns.
