# Context Manager Requirements and Phases

## Requirements (brief)
- Preserve full chat transcript in markdown as today.
- Add opt-in “Endless” mode using a context manager instead of append-all history.
- Context manager consumes a named template (path/name provided by UI/directive).
- Template resolution: vault `AssistantMD/ContextTemplates/` first, then `system/ContextTemplates/`; record source/hash.
- Produce curated working view driven by templates; fail open to a normal chat run if management fails.
- Persist managed views to SQLite in `system/` with observability (template metadata, included sections, budget stats).
- Keep manager reusable for future workflow directive (`@context-helper templatename`).
- Use the same model as the chat selection or workflow `@model`; route through existing `core/llm` agent creation; record model alias used.

## Phases

1) Templates & Loader (done/ready)
- Default template shipped in `system/ContextTemplates/`; resolve vault → system with hash/source metadata.
- Templates remain markdown prompts with optional JSON contract block; missing placeholders render empty.

2) Manager Core (partially done)
- Inputs assembled in chat layer and passed as a `context_payload`; currently simplified to the latest user input and recent message history.
- Manager originally enforced JSON-only via `output_type=Dict[str, Any]` using template instructions + system note; this is temporarily disabled while we debug provider differences (OpenAI Responses vs. others) and output validation.
- Drop-order/token budgeting deferred; add sections-included/budget observability if/when we add truncation logic.
- Fail-open: if management fails, proceed with normal chat prompt (no managed preamble).

3) SQLite Store (done)
- `system/context_manager.db` with `sessions` and `context_summaries`; DAL inserts template metadata, model alias, raw/parsed output, managed prompt, input payload.

4) Chat Integration (“Endless” Mode) (refactored to history_processor)
- UI toggle + template dropdown wired; managed-context mode attaches a history_processor built via `build_context_manager_history_processor`.
- Manager now runs stateless (no message_history), prompt = manager prompt + template + rendered recent turns + latest input; minimal manager instruction stays in agent.instructions; output treated as natural language.
- History processor injects one system message (“Context summary (managed): …”) before the recent non-tool turns and persists the managed view; chat executor is clean again (no inline management/persistence).
- Markdown transcript unchanged; template source/hash recorded.
- New direction: simplify by using Pydantic AI `history_processors` on the chat agent. The processor will (per user turn) slice/reshape history, run the manager, and return the curated message stack (e.g., prepend system message with managed summary). Transcript storage stays untouched; avoid recursion by keeping the manager’s agent processor-free and run it once per turn, caching the result for persistence. See https://ai.pydantic.dev/message-history/#processing-message-history

5) Tests & Observability (pending/partial)
- Need unit coverage for template resolution and manager fallback; add integration scenarios for Endless mode; add tracing for history lengths/outputs. Drop-order tests only if truncation is added later.

6) Workflow Directive (later)
- Add `@context-helper <template>` directive to workflow steps reusing the manager; respect fail-open semantics.

### Additional Implementation Notes
- Start simple: use template instructions directly; optional YAML/JSON schema in the template is advisory only (no dynamic Pydantic model/validation). Manager now enforces JSON-only via `output_type=Dict[str, Any]` but still stores raw output for observability.
- Drop-order/token budgeting is deferred; templates can self-limit (e.g., “3-4 sentences”). Add truncation rules later if needed.
- Reflections: data lives in manager state; template exposes it via a placeholder/key. Decide generation triggers (e.g., every N turns or on tool failures).
- Progress so far:
  - UI: “Endless” mode and template dropdown added; templates listed via `/api/context/templates` (vault + system).
  - Settings:
    - `context_manager_recent_runs`: runs fed to the manager; blank/0 disables the manager (falls back to raw history).
    - `context_manager_passthrough_runs`: runs passed verbatim to the chat model with the summary; blank/0 disables passthrough (summary-only when managing).
    - `context_manager_token_threshold`: measured against full `message_history`; below threshold skips management for that turn (no summary injection). Blank/0 disables the gate (manage every turn unless the manager itself is disabled).
- Manager: stateless; template + rendered recent turns + latest input form the prompt; minimal manager instruction in agent.instructions; output is natural language (no JSON parse). Persistence happens in the history processor.
- History handling: history_processor injects managed summary (system message) + recent non-tool turns. Tool calls/results are currently dropped; if we need tool context, we must include paired tool messages or render tool summaries to avoid the “tool call/return pairing” warning.
- Chat integration: chat executor just sets instructions, attaches the history processor in managed-context mode, and runs the chat agent; no inline management or persistence.
- Storage: `context_manager.db` with sessions/context_summaries; observability includes raw output and input payload.
- Gaps: tool history gap (see above), provider placement/rules still to be validated, integration tests pending.
