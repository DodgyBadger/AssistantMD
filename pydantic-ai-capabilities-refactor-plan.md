# Pydantic AI Capabilities Refactor Plan

## Research Summary

Pydantic AI now positions capabilities as the primary extension point for reusable agent behavior. A capability can bundle tools, lifecycle hooks, instructions, model settings, and history processing behind the `Agent(..., capabilities=[...])` surface. Built-in capabilities include hooks, provider-adaptive web search/fetch/image/MCP, tool preparation, tool metadata, return schema injection, history processors, thinking, and thread executor support.

The Pydantic AI Harness repository is the official external capability library. As of the reviewed README, it ships Code Mode and tracks a broader capability matrix covering file system, shell, repo context injection, verification loops, context management, skills, planning, task tracking, guardrails, token/cost budgets, tool approval, secret masking, tool budgets, loop detection, tool error recovery, and current-time injection. The harness package requires `pydantic-ai-slim>=1.80.0`; AssistantMD is moving from `pydantic-ai==1.77.0` to a newer pinned Pydantic AI release so this refactor can use the current capability surface directly.

AssistantMD already has important capability-like implementations. `_build_chat_tool_overflow_capability()` in `core/chat/executor.py` creates a Pydantic AI `Hooks` capability to persist tool events and route oversized tool results into the authoring cache. The chat context manager is also capability-shaped: `core/chat/executor.py` builds context-template history processors through `build_context_manager_history_processor(...)` and passes them directly to the agent. Both should become named AssistantMD capabilities before evaluating any harness replacement.

## Relevant External References

- Pydantic AI capabilities docs: `https://pydantic.dev/docs/ai/core-concepts/capabilities`
- Pydantic AI Harness overview: `https://pydantic.dev/docs/ai/harness/overview`
- Pydantic AI Harness repository: `https://github.com/pydantic/pydantic-ai-harness`

## Local Architecture Fit

Current AssistantMD surfaces that map naturally to capabilities:

- `core/llm/agents.py`: already accepts `capabilities` and passes them to `Agent`.
- `core/chat/executor.py`: owns chat preflight, history processors, tool event persistence, and oversized tool output cache routing.
- `core/authoring/shared/tool_binding.py`: resolves settings-backed AssistantMD `BaseTool` tools into Pydantic AI tool functions.
- `core/authoring/context_manager.py`: provides history processing/context assembly that can be exposed via `HistoryProcessor` or a custom capability.
- `core/runtime/buffers.py` and `core/authoring/cache.py`: provide the runtime state backing AssistantMD-specific capability behavior.
- `core/settings/store.py` and settings templates: own user-visible tool availability and should remain the authority for enabling AssistantMD tools or optional external capabilities.

## Guiding Decision

Do not replace AssistantMD's current vault-aware tools with harness tools as the first step. AssistantMD tools encode product-specific contracts: vault scoping, safe/unsafe file boundaries, multimodal read behavior, output routing, persistent cache refs, chat tool event persistence, and validation scenarios. The lower-risk refactor is to package these behaviors in the Pydantic AI capability style so external harness capabilities can be added beside them later.

The first implementation milestone must be behavior-preserving. The current dev branch behavior is the contract: architecture may move behind clearer capability boundaries, but chat results, context assembly, tool availability, tool events, cache refs, cache notices, Monty helper behavior, and API payloads should not intentionally change.

Longer term, the wrapper should shrink into a tool binding adapter. Cross-tool adapter policy can live in `AssistantMDToolsCapability`; post-tool lifecycle behavior should live in hook-based capabilities; intrinsic tool defaults should live on `BaseTool`.

## Proposed Scope

1. Create a local `core/llm/capabilities/` package for AssistantMD-owned capabilities.
2. Move chat tool event persistence and oversized output cache routing from `core/chat/executor.py` into a named capability, likely `ChatToolOutputCacheCapability`.
3. Move chat context-template history processing into a named capability, likely `AssistantMDChatContextCapability`, while preserving `build_context_manager_history_processor(...)` as the behavior source in the first pass.
4. Audit legacy output and tool routing paths to separate current Monty helper behavior from deprecated DSL behavior.
5. Add a local tool capability adapter that can expose settings-resolved AssistantMD tools as a Pydantic AI capability without preserving dead DSL wrapper behavior unless a validation scenario proves it is still live.
6. Add a capability composition helper for chat runs so `_prepare_chat_execution()` assembles context, tool-output-cache, and future capabilities in one place.
7. Add the harness package as an available dependency, but keep feature adoption behind explicit AssistantMD settings/adapters rather than enabling harness capabilities globally.

## Proposed Module Shape

- `core/llm/capabilities/__init__.py`
- `core/llm/capabilities/chat_tool_output_cache.py`
  - Owns hook registration for `before_tool_execute` and `after_tool_execute`.
  - Depends on injected session/vault/cache settings rather than module globals where practical.
  - Preserves existing tool event rows, cache refs, metadata, notices, and multimodal bypass behavior.
- `core/llm/capabilities/assistant_tools.py`
  - Wraps settings-resolved AssistantMD tool callables as Pydantic AI capabilities.
  - Uses `Toolset(FunctionToolset(...))` for tool exposure and `PrepareTools(...)` for shared tool-definition policy.
  - Keeps `core/authoring/shared/tool_binding.py` as the single source for loading AssistantMD `BaseTool` classes and preserving live execution behavior.
  - Exposes live AssistantMD tool behavior only: settings/secrets filtering, `BaseTool` loading, sync/async compatibility, `RunContext` injection, no-argument instruction fallback, and Monty helper compatibility.
  - Cross-tool runtime policy belongs here when it must be applied uniformly at the Pydantic tool boundary.
  - Static tool instructions, documentation pointers, metadata conventions, and reusable tool-authoring helpers should move toward `BaseTool` where practical.
  - Does not carry forward legacy `output=`, `write_mode=`, buffer, or variable routing.
- `core/llm/capabilities/chat_context.py`
  - Wraps context-template history processors as a named capability using Pydantic AI's built-in `HistoryProcessor` capability if the upgraded API supports the needed shape, otherwise a small custom capability.
  - Keeps `core/authoring/context_manager.py` and `build_context_manager_history_processor(...)` as the source of behavior during the first refactor.
  - Preserves template fallback ordering, failure logging, context cache semantics, and latest-turn handling.
- `core/llm/capabilities/factory.py`
  - Centralizes chat capability composition from vault/session/model/tool settings.

## Dependency Upgrade Slice

- Pin `pydantic-ai==1.85.1`, the latest package index version found during planning.
- Pin `pydantic-ai-harness[code-mode]==0.1.2`, the latest harness package index version found during planning.
- Refresh `docker/uv.lock` from `docker/pyproject.toml`.
- Run targeted import and construction smoke tests around AssistantMD's Pydantic AI surfaces before any behavior refactor:
  - `core.llm.agents.create_agent`
  - `pydantic_ai.capabilities.Hooks`
  - `pydantic_ai_harness.CodeMode`
  - `pydantic_ai.messages.ToolReturn`
  - `pydantic_ai.tools.Tool`
- Do not enable Code Mode, MCP, WebSearch/WebFetch, or other new capabilities by default as part of the dependency bump.

## Tool Wrapper Audit

Current findings from repository search:

- Monty `call_tool(...)` (`core/authoring/helpers/call_tool.py`) forwards only `arguments` to resolved tools and rejects non-empty `options`.
- Monty `generate(..., tools=[...])` also resolves tools through `resolve_tool_binding(...)`.
- `core/authoring/helpers/runtime_common.py` still creates run/session buffer stores in `RunContext.deps`, but the direct Monty helper contract returns inline `CallToolResult` output and metadata.
- Legacy tool-call routing has been removed from `core/authoring/shared/tool_binding.py`.
- The legacy typed `output(...)` target parsing/writing path was orphaned after the Monty helper transition and has been removed with the low-level output routing module.
- `core/constants.py::TOOL_ROUTING_GUIDANCE` has been removed.

`output=`, `write_mode=`, variable routing, and buffer routing in the tool wrapper were DSL relics. Current Monty helper paths continue to use explicit `call_tool(...)` arguments and typed `output(...)` helpers.

Wrapper responsibility target:

- `AssistantMDToolsCapability`: settings/secrets filtering, `BaseTool` loading, `RunContext` injection, sync/async adaptation, Pydantic tool construction, and any deliberate cross-tool call policy.
- `BaseTool`: per-tool instructions, docs metadata, stable tool authoring conventions, and reusable helper methods.
- `ChatToolOutputCacheCapability`: after-tool result observation, tool event persistence, token counting, spill-to-cache, multimodal bypass, vault-backed file-ref guidance, and cache notice replacement.
- Later hardening slice: consider whether remaining `BufferStore` plumbing is still needed outside typed authoring output helpers.

## Compatibility Notes

- Pydantic AI capability APIs are evolving quickly. Prefer a thin local boundary so future API changes are localized.
- Harness is versioned `0.x`; treat it as optional until an explicit compatibility and contract test pass is complete.
- AssistantMD chat has an explicit instruction layering contract: base instructions from `core/constants.py`, then AssistantMD tool descriptions/guidance, then context-template injected history/messages. AssistantMD tool registration may use Pydantic AI tool capabilities, but AssistantMD's long tool guidance should remain an explicit ordered instruction layer.
- Third-party capabilities that only register tools/hooks/processors can be attached directly after compatibility testing. Third-party capabilities that inject behavioral instructions should be wrapped or adapted so AssistantMD chooses where those instructions land relative to base instructions, AssistantMD tool guidance, and context-template output.

## Validation Target

Primary validation scenario to preserve behavior:

- `validation/scenarios/integration/core/chat_tool_overflow_cache.py`

Additional scenarios to request from maintainers after implementation:

- `validation/scenarios/integration/core/chat_session_persistence_contract.py`
- `validation/scenarios/integration/core/chat_tool_metadata_visibility.py`
- `validation/scenarios/integration/core/code_execution_local.py`
- `validation/scenarios/integration/core/chat_cache_multi_pass.py`
- context-template scenarios that cover history shaping and context cache behavior, if maintainers have them enabled in the target run

Agents should use targeted local smoke checks for import/type regressions, then request maintainer validation rather than running the full suite.

No-behavior-change checks to emphasize:

- Same selected tools become available for chat and Monty `call_tool(...)`.
- Same missing-secret tools are skipped with equivalent warnings.
- Same chat tool event rows are recorded for calls/results/overflow cache.
- Same oversized result cache refs and model-facing cache notices are produced.
- Same multimodal tool results bypass text cache serialization.
- Same context-template fallback and latest-turn preservation occur.
- Same authoring helper contracts return inline `CallToolResult` output and metadata.

## Contract-Sensitive Areas

- Chat tool event schema and API payloads: `chat_tool_events`, `artifact_ref`, `result_text`, `result_metadata`.
- Cache refs and owner IDs for oversized chat tool outputs.
- Tool routing parameters: `output`, `write_mode`, directive-level params, session buffer store behavior.
- Multimodal `ToolReturn` handling must remain inline and must not be serialized into cache text.
- Vault-backed file read behavior must continue returning file-ref guidance instead of caching vault file contents.
- Context-template fallback behavior must remain stable: explicit template, global default template, then `default.md`.
- Context manager cache behavior and validation/logging events must remain stable.
- Latest user turn preservation must remain stable when history processors rewrite or replace prior context.
- Settings and secrets remain authoritative for tool availability and skipped-tool warnings.
- Runtime state under `/app/data` and `/app/system` must be treated as persistent during local checks.

Dead-code-sensitive areas audited/removed:

- `TOOLS_ALLOWED_PARAMETERS` in `core/authoring/shared/tool_binding.py`
- `_wrap_tool_function(...)` output/write-mode signature mutation
- `route_tool_output(...)`
- `TOOL_ROUTING_GUIDANCE`
- `routing_allowed_tools` default setting and accessor

Current `BufferStore` status:

- The overflow cache does not use `BufferStore`; it uses `core/authoring/cache.py`.
- Chat and Monty `call_tool(...)` still pass `BufferStore` instances through `RunContext.deps` as a compatibility surface for tools.
- The orphaned typed output writer path that used `BufferStore` for variable-style output has been removed.
- Further removal of `BufferStore` itself should wait until tool dependency contracts are audited.

Follow-up cleanup:

- Return to `BufferStore` after this capability refactor lands and remove the in-memory buffer dependency surface if targeted tool validation confirms no live tool reads `ctx.deps.buffer_store` or `ctx.deps.buffer_store_registry`.
- That follow-up should remove `BufferStore` from chat deps, `WorkflowAuthoringHost`, `invoke_bound_tool(...)`, and runtime context session state in one focused cleanup commit.

## Next Implementation Steps

1. Add focused unit coverage for capability construction where practical, plus preserve/extend the `chat_tool_overflow_cache` integration scenario expectations if the refactor changes observable event ordering or metadata.
2. Add or identify targeted context-manager scenario assertions for template fallback, context cache decisions, and latest-turn preservation.
3. Audit whether any live tools still require `buffer_store` or `buffer_store_registry` in `RunContext.deps`; if not, remove `BufferStore` from chat deps, authoring host state, `invoke_bound_tool(...)`, and runtime context session state.
4. Evaluate harness `CodeMode` and core provider-adaptive capabilities in isolated settings-backed experiments after AssistantMD-owned capabilities are stable.
5. Prepare a review-ready diff with clear commit boundaries: dependency upgrade, capability extraction, deprecated DSL cleanup, and documentation/settings cleanup.

## Implementation Progress

- Completed dependency upgrade in `docker/pyproject.toml` and `docker/uv.lock`: `pydantic-ai==1.85.1` and `pydantic-ai-harness[code-mode]==0.1.2`.
- Added `core/llm/capabilities/` with chat context, chat tool output cache, and chat capability composition modules.
- Rewired `core/chat/executor.py` to compose context management and chat tool output cache behavior through capabilities.
- Added `core/llm/capabilities/assistant_tools.py` using Pydantic AI `Toolset(FunctionToolset(...))` and `PrepareTools(...)` for AssistantMD tool exposure and common tool-definition metadata.
- Rewired chat and Monty `generate(..., tools=[...])` to use the AssistantMD tools capability adapter.
- Removed legacy DSL-era tool-call output routing from the tool binding wrapper.
- Removed the deprecated `routing_allowed_tools` setting from the seed template and local settings store.
- Removed the orphaned typed output routing modules: `core/authoring/shared/output_resolution.py` and `core/utils/routing.py`.
- Removed unused `OutputItem`/`OutputResult` contracts that belonged to the removed output helper surface.
- Updated `docs/architecture/llm-tools.md` to describe the capability model.

## Recommended Next Phase

Move to Refactor and Hardening for the next slice: audit remaining `BufferStore` and wrapper responsibilities, add focused construction coverage for the new capability adapters, and prepare isolated experiments for optional third-party capabilities.
