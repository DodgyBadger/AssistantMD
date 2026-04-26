# Delegate Tool Implementation Plan

## Goal

Add a first-class `delegate` tool that lets the chat agent launch a bounded child agent for multi-step work, and expose the same callable directly to Monty scripts through the direct-tool bridge.

If validation shows this is stable, authored scripts should move from `generate(...)` to `delegate(...)` for model reasoning. `generate(...)` can then be removed from the preferred script surface, and eventually removed entirely before this branch merges.

The child agent must have the same multimodal capabilities and payload semantics as normal chat. Chat and delegate must not assemble provider payloads through parallel, diverging implementations.

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

```python
image = await file_ops_safe(operation="read", path="Math/page_images/page-1.png")
result = await delegate(
    prompt="Review this worksheet image and identify the main exercise.",
    inputs=image.items,
    model="gpt-mini",
)
```

Tool result shape should be script-friendly and compatible with the existing direct-tool bridge:

- `output`: child agent final response
- `metadata`: model, tool list, input counts, attached media counts, child run identifiers, warnings
- `content`: optional raw payload if needed later
- `items`: normalized artifacts only if the child produces reusable source artifacts

## Architecture

Introduce a shared lower-level service, not a chat-executor call:

```text
core/agent_runs/
  service.py
  contracts.py
```

The service must use the same multimodal payload assembly contract as chat. If normal chat currently owns image path/upload handling separately from authored artifact handling, extract a shared assembly module first and make both chat and delegate call it.

Shared assembly must cover:

- direct uploaded images
- vault image paths
- `RetrievedItem` image artifacts
- markdown text with embedded local images
- ordered interleaving of text and image parts
- size limits and vision-capability checks
- warnings and attachment counts
- history-safe text for persistence/logging

The service should run one bounded Pydantic AI agent with:

- prompt
- optional `RetrievedItem` inputs
- optional tool allowlist
- model and thinking options
- vault path/name
- session/run buffer stores
- optional inherited message history
- max tool turns / timeout controls

`core/tools/delegate.py` becomes a normal `BaseTool` wrapper over that service. Because Monty now exposes configured tools directly, scripts get `await delegate(...)` without a separate helper implementation.

## Non-Goals

- Do not call `core.chat.executor.execute_chat_prompt(...)` from the delegate tool.
- Do not persist child agent messages into the parent chat transcript by default.
- Do not run context templates inside child agents by default.
- Do not allow unbounded recursive delegation.
- Do not make `generate(inputs=...)` accept arbitrary dictionaries as a workaround.

## Key Design Decisions

- Child agent runs are isolated by default, with explicit optional inheritance of curated history later.
- `delegate` excludes `delegate` and `code_execution_local` from child tool access by default.
- `delegate` accepts `inputs` using the same `RetrievedItem` contract currently used by `generate`.
- Chat and `delegate` share one multimodal renderer for local files, uploaded images, image artifacts, and markdown-with-local-images.
- URL/web multimodal rendering is out of scope for the first pass; web/browser results are plain text artifacts unless a later URL artifact renderer is added.
- `generate(...)` remains during the first implementation only as a compatibility baseline and comparison target.

## Proposed API

```python
result = await delegate(
    prompt: str,
    inputs: RetrieveResult | RetrievedItem | list[RetrievedItem] | tuple[RetrievedItem, ...] | None = None,
    instructions: str | None = None,
    model: str | None = None,
    tools: list[str] | tuple[str, ...] | None = None,
    options: dict | None = None,
)
```

Initial `options` keys:

- `thinking`: same semantics as `generate`
- `max_tool_calls`: default small bounded value
- `timeout_seconds`: conservative default
- `history`: `"none"` initially; reserve `"session"` or `"provided"` for later

## Implementation Steps

1. Add shared contracts.
   - `AgentRunRequest`
   - `AgentRunResult`
   - input artifact normalization helper reused by chat/delegate/script surfaces

2. Extract shared multimodal input assembly if needed.
   - Move chat image path/upload assembly and artifact input assembly behind one module.
   - Preserve current chat behavior exactly.
   - Make normal chat execution use the extracted module before wiring delegate.
   - Make delegate use the same module.
   - Add tests that compare chat and delegate assembly metadata for equivalent image/path inputs.

3. Add shared service.
   - Build prompt payload through the shared multimodal input assembly module.
   - Resolve model/thinking with existing model factory logic.
   - Resolve child tool allowlist with `resolve_tool_binding`.
   - Remove unsafe recursive tools from the child allowlist.
   - Run a Pydantic AI agent with AssistantMD tool capabilities.
   - Return a structured result with output and metadata.

4. Add `core/tools/delegate.py`.
   - Implement as a `BaseTool`.
   - Accept JSON-serializable tool arguments from chat.
   - Convert chat arguments to `AgentRunRequest`.
   - Return `ToolReturn` with metadata.
   - Keep instructions explicit about bounded child-agent use.

5. Add settings entry.
   - Add `delegate` to `system/settings.yaml` seed/default tooling if appropriate.
   - Decide whether default chat-visible state is enabled or opt-in.
   - Ensure direct Monty exposure only happens when configured.

6. Wire validation events.
   - `delegate_started`
   - `delegate_prompt_built`
   - `delegate_tool_binding_resolved`
   - `delegate_completed`
   - `delegate_failed`
   - Include child tool names, input count, attached image count, output chars, and recursion guard metadata.

7. Update Monty docs and tool docs.
   - Teach `delegate(...)` as the preferred model-reasoning primitive in scripts.
   - Keep `generate(...)` documented only as temporary compatibility during validation, or move it to an internal/deprecated section.

8. Migrate authored scripts and seed templates.
   - Replace `generate(...)` calls with `delegate(...)` where the script asks the model to reason over content.
   - Keep direct file/tool calls for deterministic retrieval and writes.

9. Remove or de-register `generate(...)` if validation is strong.
   - Remove from built-in helper registry.
   - Remove stubs and preferred docs.
   - Delete helper only after all scenarios and seed templates stop using it.

## Validation Plan

### Unit/Contract Checks

- `delegate` rejects empty prompt.
- `delegate` rejects unknown option keys.
- `delegate` rejects invalid `inputs` types.
- `delegate` normalizes `RetrievedItem`, `RetrieveResult`, and item sequences.
- `delegate` strips `delegate` and `code_execution_local` from child tools.
- `delegate` enforces `max_tool_calls` and timeout options.
- `delegate` returns stable metadata for model, tools, inputs, and attached media.

### Direct Tool Bridge Checks

- Monty type checks `await delegate(prompt="...", model="test")`.
- Monty type checks `await delegate(prompt="...", inputs=image.items, model="test")`.
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

- Shared assembly invariant:
  - Normal chat with image path and delegate with equivalent `RetrievedItem` produce the same attachment count, size-limit behavior, and vision-capability behavior.
  - Normal chat with uploaded image and delegate with equivalent artifact follow the same provider payload shape where representable.
  - Markdown-with-local-images uses the same interleaving logic in chat/delegate/script flows.

- Direct image read:
  - `image = await file_ops_safe(operation="read", path="images/test_image.jpg")`
  - `await delegate(prompt="Describe this image.", inputs=image.items, model="test")`
  - Assert one attached image in delegate prompt metadata.

- Markdown with embedded local image:
  - Read markdown containing local image ref.
  - Pass `doc.items` to `delegate`.
  - Assert image attachment count and no provider tool-call pairing errors.

- Multiple images:
  - Pass a list of image-backed `RetrievedItem`s.
  - Assert ordering is preserved and attachment count matches.

- Vision-disabled model:
  - Pass image input to a non-vision model alias.
  - Assert a clear capability error or markdown/image marker fallback, whichever policy is chosen.

### Tool-Using Child Agent Checks

- Child agent with `tools=["file_ops_safe"]` reads a file and summarizes it.
- Child agent with no tools cannot read files except through provided `inputs`.
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

- A Monty script reads several PNG/JPG files with `file_ops_safe`.
- It passes them to `delegate(inputs=...)`.
- The provider request preserves tool call/result pairs across all parent and child turns.
- No `No tool call found for function call output` error occurs.
- The fix is not achieved by a delegate-only multimodal path; normal chat and delegate continue sharing the same assembly module.

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
- Payload assembly drift if delegate implements its own multimodal renderer instead of sharing chat assembly.
- Tool-result cache ownership may need a child run/session key.
- `delegate` may be too powerful for default chat visibility; settings defaults need care.
- Removing `generate(...)` too early could break templates before the replacement contract is fully validated.

## Decision Gate For Removing `generate`

Remove `generate(...)` from the authored script surface only after:

- `delegate` passes text, image, markdown-with-images, and child-tool scenarios.
- Chat and delegate multimodal assembly share one implementation and parity tests pass.
- All seed templates and validation authoring snippets are migrated.
- The authoring LLM docs clearly teach `delegate` for model reasoning.
- There is no remaining preferred doc path that recommends `generate`.
- Maintainers agree that a single-agent-run primitive is acceptable for script model calls.

## Next Phase

Move to feature development:

1. Implement `core/agent_runs` service and `core/tools/delegate.py`.
2. Add `delegate` settings entry and docs.
3. Add `integration/core/delegate_tool.py` before migrating existing scripts.

## Status

**Implemented (steps 1–7 complete).**

### What was built

- `core/tools/delegate.py` — `DelegateTool(BaseTool)` registered in `system/settings.yaml` and `core/settings/settings.template.yaml`.
- Shared helpers extracted to avoid divergent code paths: `build_input_file_data` in `runtime_common.py`, `_THINKING_UNSET` sentinel and `resolve_effective_thinking` in `execution_prep.py`. `generate.py` imports from these shared locations.
- Validation events: `delegate_started`, `delegate_tool_binding_resolved`, `delegate_completed`, `delegate_failed`.
- `integration/core/delegate_tool.py` — covers chat-path tool calling (basic, forbidden stripping, child tools) and Monty direct-tool path.
- `integration/core/authoring_contract.py` — extended to exercise delegate via the Monty direct-tool bridge.
- `docs/tools/delegate.md` and `docs/tools/index.md` added; `docs/tools/code_execution_local.md` updated.

### Key design divergence from plan

The `inputs` parameter and the `core/agent_runs/` shared-assembly service were **not implemented**. The original plan assumed delegate needed to embed file content into the child agent's prompt (matching the `generate` pattern). In practice, delegate creates an agent — so file access belongs to the child agent via `tools=["file_ops_safe"]`, exactly as the parent agent works. The `inputs` complexity was removed entirely. Monty scripts that have already retrieved content can pass it in the prompt string; a wrapper layer can handle `RetrievedItem` translation if that proves necessary.

The multimodal parity checks in the Validation Plan are therefore moot for this implementation: there is no separate delegate assembly path to keep in sync.

### Remaining

- Step 8: migrate authored scripts and seed templates from `generate(...)` to `delegate(...)`.
- Step 9: remove or de-register `generate(...)` once migration is validated.
