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

1) Templates & Loader ✅
2) Manager Core ✅
3) SQLite Store ✅
4) Chat Integration ("Managed Context" Mode) ✅
5) Tests & Observability ✅

6) Workflow Directive (later)
- Add `@context-helper <template>` directive to workflow steps reusing the manager; respect fail-open semantics.

7) Parser Upgrade ✅
- Add `require_frontmatter: bool = True` to `parse_workflow_file()` so workflows keep current behavior.
- When `require_frontmatter=False` and content does not start with `---`, skip frontmatter parsing, use `{}` config, and parse sections from the full content.
- Always return `__FRONTMATTER_CONFIG__` so existing workflow callers do not break.
- Context templates can call `parse_workflow_file(..., require_frontmatter=False)` to reuse the splitter.

8) Template Directives & Overrides ✅
- Directives live inside the selected template section (same rules as workflow steps; directives at top only).
- Precedence for config: global settings → template section directives (directives win).
- Support existing directives:
  - `@model` (use existing ModelDirective to select manager model).
  - `@tools` (use existing ToolsDirective to load tools for the manager agent).
- Add new directive processors for overrides (simple int/blank parsing):
  - `@recent-runs` (overrides context_manager_recent_runs)
  - `@passthrough-runs` (overrides context_manager_passthrough_runs)
  - `@token-threshold` (overrides context_manager_token_threshold)
  - `@recent-summaries` (new; controls how many prior summaries to include in the manager prompt)
  - can also use `@input-file` (but ignores required=true as not currently relevant)
- Add a new global setting `context_manager_recent_summaries` (default TBD) and use it when no directive is present.

9) Context Manager Wiring ✅
- Template selection rules: use `## Instructions` section if present; then use the first section after it as the template body. Ignore any remaining sections for now.
- Parse directives from the selected section and use the cleaned section content as the template body.
- Manager prompt should include N prior summaries (per setting/directive) instead of hardcoded latest-only.
- Manager agent should accept optional tool instructions + tools from `@tools`, and use model override from `@model`.

10) New Context Management Tools (TBD)
- Define optional tools for the manager (e.g., subagents, vector search, or file_ops_safe for transcript reads).
- Wire manager tools through @tools directives once tool definitions are available.

### Additional Implementation Notes

