# LLM + Tools Subsystem

This subsystem builds agents, resolves model aliases, loads tools, and handles chat tool output caching.

## Primary code

- `core/llm/agents.py`
- `core/llm/capabilities/`
- `core/llm/chat_executor.py`
- `core/directives/model.py`
- `core/directives/tools.py`
- `core/tools/`

Current web-oriented tools under `core/tools/` include search (`web_search_*`),
API-driven extraction (`tavily_extract`, `tavily_crawl`), and browser-backed
extraction (`browser`).

## Responsibilities

- Build configured Pydantic AI agents for chat/workflow/context runs.
- Resolve model aliases through settings-backed provider/model mapping.
- Resolve tool IDs to tool classes/functions from settings.
- Inject tool usage instructions into agents.
- Compose AssistantMD-owned Pydantic AI capabilities for tool exposure, chat context, and tool result handling.
- Store oversized chat tool output in cache and return compact cache refs.

## Chat execution flow (high level)

1. Resolve model and tools from request + settings.
2. Build agent with AssistantMD capabilities for tool exposure, context management, and tool result handling.
3. Execute prompt (streaming or non-streaming).
4. Persist session history to markdown.
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
- `@tools` processing imports configured modules and finds `BaseTool` subclasses.
- Chat and `generate(..., tools=[...])` attach tools through `core/llm/capabilities/assistant_tools.py`.
- Tool result caching is handled by chat capabilities rather than tool-call routing parameters.
- Oversized chat tool output is stored through the authoring cache layer, not the legacy in-memory buffer store.
- `BufferStore` remains available on `RunContext.deps` for tool compatibility; the deprecated typed output-routing modules that wrote variable-style buffers have been removed.
