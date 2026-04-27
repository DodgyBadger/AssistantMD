# LLM + Tools Subsystem

This subsystem builds agents, resolves model aliases, binds settings-backed tools, and composes Pydantic AI capabilities for chat, delegate, and authored direct-tool execution.

## Primary code

- `core/llm/agents.py`
- `core/llm/capabilities/`
- `core/chat/executor.py`
- `core/authoring/shared/tool_binding.py`
- `core/tools/`

Configured built-in tools include vault file access (`file_ops_safe`, `file_ops_unsafe`), constrained local Python (`code_execution`), child-agent delegation (`delegate`), workflow execution (`workflow_run`), and web search/extraction (`web_search_*`, `tavily_extract`, `tavily_crawl`, `browser`). Additional tool modules may exist under `core/tools/`, but they are available to agents only when present in the settings-backed tool registry.

## Responsibilities

- Build configured Pydantic AI agents for chat/workflow/context runs.
- Resolve model aliases through settings-backed provider/model mapping.
- Resolve tool IDs to tool classes/functions from settings through the shared tool-binding layer.
- Expose concise tool definitions and virtual-doc pointers to agents.
- Compose AssistantMD-owned Pydantic AI capabilities for tool exposure, chat context, and tool result handling.
- Store oversized chat tool output in cache and return compact cache refs.
- Wrap web-derived tool results with untrusted-data boundaries.

## Chat execution flow (high level)

1. Resolve model and tools from request + settings.
2. Build agent with AssistantMD capabilities for tool exposure, context management, and tool result handling.
3. Execute prompt (streaming or non-streaming).
4. Persist provider-native session history to the chat SQLite store.
5. Emit tool activity metadata/events.

## Capability model

AssistantMD-owned Pydantic AI capabilities live under `core/llm/capabilities/`.

- `chat_context.py` wraps context-template history processing as a named capability.
- `chat_tool_output_cache.py` persists tool call/result events and routes oversized chat tool output to cache through tool lifecycle hooks.
- `assistant_tools.py` exposes settings-resolved AssistantMD tools through Pydantic AI `Toolset(FunctionToolset(...))` and applies shared tool-definition policy through `PrepareTools(...)`.
- `factory.py` composes chat capabilities for normal and streaming chat execution.

These capabilities preserve the existing chat contracts while moving cross-cutting
agent behavior toward Pydantic AI's composable capability model.

## Tool loading model

- Tool registry source is settings (`tools` section in settings store).
- `resolve_tool_binding(...)` imports configured modules and finds `BaseTool` subclasses.
- Chat, delegate child agents, and authored direct-tool calls attach tools through `core/llm/capabilities/assistant_tools.py`.
- Tool result caching is handled by chat capabilities rather than tool-call routing parameters.
- Oversized chat tool output is stored through the authoring cache layer, not the legacy in-memory buffer store.
- `BufferStore` remains available on `RunContext.deps` for tool compatibility; the deprecated typed output-routing modules that wrote variable-style buffers have been removed.

## Delegate and Code Execution

`delegate` creates a bounded child agent with an isolated prompt, optional model alias, optional tool list, and internal tool-call/timeout guardrails. Completed and bounded-failure returns include compact audit metadata summarizing child tool calls, return previews, and tool errors.

`code_execution` runs constrained Monty Python in the active chat session. It shares the authoring runtime and helper/tool surface used by workflow and context scripts, but is exposed as a normal chat tool.
