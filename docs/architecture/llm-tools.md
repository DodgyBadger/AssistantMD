# LLM + Tools Subsystem

This subsystem builds agents, resolves model aliases, loads tools, and routes tool output behavior.

## Primary code

- `core/llm/agents.py`
- `core/llm/chat_executor.py`
- `core/directives/model.py`
- `core/directives/tools.py`
- `core/tools/`

## Responsibilities

- Build configured Pydantic AI agents for chat/workflow/context runs.
- Resolve model aliases through settings-backed provider/model mapping.
- Resolve tool IDs to tool classes/functions from settings.
- Inject tool usage instructions into agents.
- Support tool output routing to inline/file/variable based on allowlist and params.

## Chat execution flow (high level)

1. Resolve model and tools from request + settings.
2. Build agent with optional history processors (context manager).
3. Execute prompt (streaming or non-streaming).
4. Persist session history to markdown.
5. Emit tool activity metadata/events.

## Tool loading model

- Tool registry source is settings (`tools` section in settings store).
- `@tools` processing imports configured modules and finds `BaseTool` subclasses.
- Routing controls use directive/tool settings and runtime buffer stores.
