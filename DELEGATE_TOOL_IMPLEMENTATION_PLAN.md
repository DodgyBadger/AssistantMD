# Delegate Tool Implementation Plan

## Goal

Add a first-class `delegate` tool that lets the chat agent launch a bounded child agent for multi-step work, and expose the same callable directly to Monty scripts through the direct-tool bridge.

If validation shows this is stable, authored scripts should move from `generate(...)` to `delegate(...)` for model reasoning. `generate(...)` can then be removed from the preferred script surface, and eventually removed entirely before this branch merges.

The child agent should work like a normal delegated agent: the caller gives it a goal, relevant paths or URLs, and the tools it may use. `delegate` is not a payload-transport primitive and should not expose Python-only objects such as `RetrievedItem` in its LLM-facing schema.

## Problem Statement

`generate(...)` has drifted beyond its name and expected contract:

- it accepts multimodal inputs
- it can expose tools
- it creates an agent internally
- it caches
- it is expected to reason over artifacts, not just produce text

This confuses both human authors and the authoring agent. A direct `delegate(...)` tool communicates the actual behavior better: run a child agent over a prompt, optional inputs, and optional tools.

## Target Contract

Chat agent use:

```text
Use delegate when a task needs a focused child agent to inspect files, images, URLs, or tool outputs and return a report.
```

Monty script use:

result = await delegate(
    prompt="Read Math/page_images/page-1.png and identify the main exercise.",
    tools=["file_ops_safe"],
    model="gpt-mini",
)
```

Tool result shape should be script-friendly and compatible with the existing direct-tool bridge:

- `output`: child agent final response
- `metadata`: model, tool list, input counts, attached media counts, child run identifiers, warnings
- `content`: optional raw payload if needed later
- `items`: normalized artifacts only if the child produces reusable source artifacts

## Architecture

`core/tools/delegate.py` is a normal `BaseTool` wrapper that runs one bounded Pydantic AI child agent with:

- prompt
- optional tool allowlist
- model and thinking options
- vault path/name
- session/run buffer stores
- max tool turns / timeout controls

Because Monty now exposes configured tools directly, scripts get `await delegate(...)` without a separate helper implementation.

## Non-Goals

- Do not call `core.chat.executor.execute_chat_prompt(...)` from the delegate tool.
- Do not persist child agent messages into the parent chat transcript by default.
- Do not run context templates inside child agents by default.
- Do not allow unbounded recursive delegation.
- Do not make `generate(inputs=...)` accept arbitrary dictionaries as a workaround.
- Do not add Python-object parameters such as `RetrievedItem` to the LLM-facing tool schema.

## Key Design Decisions

- Child agent runs are isolated by default, with explicit optional inheritance of curated history later.
- `delegate` excludes `delegate` and `code_execution_local` from child tool access by default.
- `delegate` accepts JSON-shaped arguments suitable for both chat tools and Monty direct calls.
- Source access is agentic: pass paths, URLs, or inline text in the prompt and grant the child agent the tools it needs.
- Local markdown/images use the same multimodal path as chat when the child calls `file_ops_safe(read)`.
- Online image fetching is out of scope until a dedicated HTTP/image fetch tool exists.
- `generate(...)` remains during the first implementation only as a compatibility baseline and comparison target.

## Proposed API

```python
result = await delegate(
    prompt: str,
    instructions: str | None = None,
    model: str | None = None,
    tools: list[str] | tuple[str, ...] | None = None,
    options: dict | None = None,
)
```

Initial `options` keys:

- `thinking`: same semantics as `generate`

Child tool-call and timeout limits are internal guardrails defined in `core.constants`, not LLM-facing options.

## Implementation Steps

1. Add `core/tools/delegate.py`.
   - Implement as a `BaseTool`.
   - Accept JSON-serializable tool arguments from chat.
   - Return `ToolReturn` with metadata.
   - Keep instructions explicit about bounded child-agent use.
   - Resolve model/thinking with existing model factory logic.
   - Resolve child tool allowlist with `resolve_tool_binding`.
   - Remove unsafe recursive tools from the child allowlist.
   - Run a Pydantic AI agent with AssistantMD tool capabilities.
   - Enforce internal `max_tool_calls` and `timeout_seconds` guardrails.

2. Add settings entry.
   - Add `delegate` to `system/settings.yaml` seed/default tooling if appropriate.
   - Decide whether default chat-visible state is enabled or opt-in.
   - Ensure direct Monty exposure only happens when configured.

3. Wire validation events.
   - `delegate_started`
   - `delegate_tool_binding_resolved`
   - `delegate_completed`
   - `delegate_failed`
   - Include child tool names, output chars, bounds, and recursion guard metadata.

4. Update Monty docs and tool docs.
   - Teach `delegate(...)` as the preferred model-reasoning primitive in scripts.
   - Keep `generate(...)` documented only as temporary compatibility during validation, or move it to an internal/deprecated section.

5. Migrate authored scripts and seed templates.
   - Replace `generate(...)` calls with `delegate(...)` where the script asks the model to reason over content.
   - Keep direct file/tool calls for deterministic retrieval and writes.

6. Remove or de-register `generate(...)` if validation is strong.
   - Remove from built-in helper registry.
   - Remove stubs and preferred docs.
   - Delete helper only after all scenarios and seed templates stop using it.

## Validation Plan

### Unit/Contract Checks

- `delegate` rejects empty prompt.
- `delegate` rejects unknown option keys.
- `delegate` strips `delegate` and `code_execution_local` from child tools.
- `delegate` enforces internal max-tool-call and timeout guardrails.
- `delegate` returns stable metadata for model, tools, bounds, and output size.

### Direct Tool Bridge Checks

- Monty type checks `await delegate(prompt="...", model="test")`.
- Monty type checks `await delegate(prompt="...", tools=["file_ops_safe"], model="test")`.
- Direct tool events include `authoring_direct_tool_started/completed` for `delegate`.
- `ScriptToolResult.output` contains the child result.
- `ScriptToolResult.metadata` includes child run metadata.

### Chat Tool Checks

- Chat agent can call `delegate` as a configured tool.
- Parent chat transcript records only the parent-visible delegate tool call/result.
- Child tool calls do not corrupt parent tool-call history.
- Child agent can use an allowed tool such as `file_ops_safe`.
- Child agent cannot recursively call `delegate` by default.
- Child agent cannot call `code_execution_local` by default.

### Multimodal Checks

- Source-access invariant:
  - A child agent granted `file_ops_safe` can read the same vault files as the parent.
  - Markdown-with-local-images uses the existing `file_ops_safe(read)` multimodal tool-return path.

- Direct image read:
  - `await delegate(prompt="Read images/test_image.jpg and describe it.", tools=["file_ops_safe"], model="test")`
  - Assert the child tool call path completes without provider tool-pairing errors.

- Markdown with embedded local image:
  - Ask delegate to read markdown containing a local image ref via `file_ops_safe`.
  - Assert no provider tool-call pairing errors.

- Script-created content:
  - Inline small generated text in the prompt.
  - Write large generated markdown/image artifacts to a vault path, then ask delegate to read that path.

### Tool-Using Child Agent Checks

- Child agent with `tools=["file_ops_safe"]` reads a file and summarizes it.
- Child agent with no tools cannot read files.
- Child agent with web/search tool enabled can use it and return a result.
- Missing secret tools are skipped with clear metadata.
- Tool result caching still works for oversized child tool outputs if the existing cache capability is attached.

### Script Migration Checks

- Default context template works after replacing `generate` with `delegate` where applicable.
- `curated_trig_context.md` works after replacing summarization `generate` calls.
- Haiku workflow/context scenarios pass after migration.
- Authoring contract scenario passes after migration.
- Pending batch and weekly scripts compile/type-check after migration.

### Regression Checks For Original Issue

- A Monty script delegates review of several PNG/JPG paths with `file_ops_safe`.
- The provider request preserves tool call/result pairs across all parent and child turns.
- No `No tool call found for function call output` error occurs.

### Scenario Targets

Extend or add scenarios:

- `integration/core/delegate_tool.py`
- `integration/core/code_execution_local.py`
- `integration/core/authoring_contract.py`
- `integration/basic_haiku_context.py`
- `integration/basic_haiku_workflow.py`
- `integration/core/chat_cache_multi_pass.py`

Run targeted validations:

```bash
python validation/run_validation.py run \
  integration/core/delegate_tool \
  integration/core/code_execution_local \
  integration/core/authoring_contract \
  integration/basic_haiku_context \
  integration/basic_haiku_workflow \
  integration/core/chat_cache_multi_pass
```

Compile checks:

```bash
python -m py_compile \
  core/agent_runs/contracts.py \
  core/agent_runs/service.py \
  core/tools/delegate.py \
  core/authoring/runtime/monty_runner.py
```

## Risks

- Recursive agent/tool loops if child tool allowlists are not constrained.
- Confusing transcript persistence if child messages leak into parent chat history.
- Context-template recursion if delegate accidentally uses normal chat execution.
- Tool-result cache ownership may need a child run/session key.
- `delegate` may be too powerful for default chat visibility; settings defaults need care.
- Removing `generate(...)` too early could break templates before the replacement contract is fully validated.

## Decision Gate For Removing `generate`

Remove `generate(...)` from the authored script surface only after:

- `delegate` passes text, image-path, markdown-with-images, child-tool, and bounds scenarios.
- All seed templates and validation authoring snippets are migrated.
- The authoring LLM docs clearly teach `delegate` for model reasoning.
- There is no remaining preferred doc path that recommends `generate`.
- Maintainers agree that a single-agent-run primitive is acceptable for script model calls.

## Next Phase

Move to feature development:

1. Harden `core/tools/delegate.py`.
2. Add `delegate` settings entry and docs.
3. Add `integration/core/delegate_tool.py` before migrating existing scripts.

## Status

**Implemented (steps 1–7 complete).**

### What was built

- `core/tools/delegate.py` — `DelegateTool(BaseTool)` registered in `system/settings.yaml` and `core/settings/settings.template.yaml`.
- Shared helpers extracted to avoid divergent code paths: `build_input_file_data` in `runtime_common.py`, `_THINKING_UNSET` sentinel and `resolve_effective_thinking` in `execution_prep.py`. `generate.py` imports from these shared locations.
- Validation events: `delegate_started`, `delegate_tool_binding_resolved`, `delegate_completed`, `delegate_failed`.
- `integration/core/delegate_tool.py` — covers chat-path tool calling (basic, forbidden stripping, child tools) and Monty direct-tool path.
- `delegate` now enforces centralized child-run bounds from `core.constants`: `max_tool_calls` through Pydantic AI `UsageLimits` and `timeout_seconds` through an async timeout.
- `integration/core/delegate_tool.py` now covers bounded defaults and a markdown-with-embedded-image source path delegated through child `file_ops_safe`.
- `integration/core/authoring_contract.py` — extended to exercise delegate via the Monty direct-tool bridge.
- `docs/tools/delegate.md` and `docs/tools/index.md` added; `docs/tools/code_execution_local.md` updated.

### Key design decision

The `inputs` parameter and the `core/agent_runs/` shared-assembly service were intentionally not implemented. `delegate` is an agentic subtask primitive, not a payload-transport primitive. File and image access belongs to the child agent through tools such as `file_ops_safe`, exactly as the parent agent works. Monty scripts that have already created text can inline it in the prompt; large or binary generated artifacts should be written to the vault and passed by path.

Multimodal behavior for local markdown/images is exercised through the child agent's tool calls. `file_ops_safe(read)` remains the shared multimodal path.

### Remaining

- Step 8: migrate authored scripts and seed templates from `generate(...)` to `delegate(...)`.
- Step 9: remove or de-register `generate(...)` once migration is validated.
