# Extending AssistantMD

Builder guide for extending AssistantMD in two places:

- Tools (`core/tools/*.py` + settings entry)
- Directives (`core/directives/*.py` + bootstrap registration)

This document is implementation-focused and maps directly to current code paths.

## Quick decision guide
- Add a **tool** when you need new runtime capabilities (e.g. API call).
- Add a **directive** when you need new control primitives in workflow/context files.
## 1) Custom tools
Purpose: give the model new runtime actions it can call (search, fetch, transform, execute, or domain-specific operations).

### Contract

Tools are classes that inherit from `BaseTool` and expose:

- `get_tool(vault_path: str | None) -> Tool`
- `get_instructions() -> str`

Relevant code:

- `core/tools/base.py`
- `core/directives/tools.py`
- `core/settings/settings.template.yaml` (`tools:` section)

### Minimal scaffold

Create `core/tools/my_tool.py`:

```python
from pydantic_ai.tools import Tool
from core.tools.base import BaseTool


class MyTool(BaseTool):
    @classmethod
    def get_tool(cls, vault_path: str | None = None):
        async def my_tool(input_text: str) -> str:
            return f"Processed: {input_text}"
        return Tool(my_tool, name="my_tool")

    @classmethod
    def get_instructions(cls) -> str:
        return "Use my_tool for domain-specific processing."
```

Register it in settings:

- For local experiments: add it to `system/settings.yaml`.
- For project/built-in tools: also add it to `core/settings/settings.template.yaml` (seed), otherwise the UI/config reconciliation may flag it as deprecated/removed.

```yaml
tools:
  my_tool:
    module: core.tools.my_tool
    description: "Domain-specific processing"
    requires_secrets: []
    user_editable: false
```

### Behavior details

- The `@tools` directive resolves tool names from settings, imports the module, and finds a `BaseTool` subclass.
- Tool availability in UI and chat/workflow usage comes from the same settings-backed catalog.
- Tool output routing (`output=...`, `write_mode=...`) is mediated by `core/directives/tools.py` and allowlist settings.

### Safety notes

- For file write/delete behavior, follow existing safe/unsafe patterns (`file_ops_safe` vs `file_ops_unsafe`).
- Keep return payloads concise when possible. Large outputs may be routed to buffers.

## 2) Custom directives
Purpose: add new markdown control syntax (`@directive`) that parses and returns structured primitives. Workflow/context engines decide how to use those primitives during orchestration.

### Contract

Directives are processors that implement `DirectiveProcessor`:

- `get_directive_name()`
- `validate_value(value: str)`
- `process_value(value: str, vault_path: str, **context)`

Relevant code:

- `core/directives/base.py`
- `core/directives/parser.py`
- `core/directives/registry.py`
- `core/directives/bootstrap.py`

### Minimal scaffold

Create `core/directives/my_directive.py`:

```python
from core.directives.base import DirectiveProcessor


class MyDirective(DirectiveProcessor):
    def get_directive_name(self) -> str:
        return "my_directive"

    def validate_value(self, value: str) -> bool:
        return bool(value and value.strip())

    def process_value(self, value: str, vault_path: str, **context):
        return value.strip()
```

Registering options:

- Quick/custom path: register at runtime from your workflow engine (or other startup path) using `register_directive(...)` or `CoreServices.register_directive(...)`.
- Built-in path (fork): if you want the directive available everywhere by default, add it centrally in `core/directives/bootstrap.py` (`_BUILTIN_DIRECTIVES`).

### Behavior details

- Parsing supports `@directive value` and `@directive: value`.
- Directive names are normalized (hyphen/underscore tolerant) in the registry lookup layer.
- Directives can appear multiple times in a section; processors should handle aggregation patterns used by their consumers.
- Directives do not execute workflow orchestration themselves; they validate/transform directive values and return data for the engine layer to consume.

## Testing

For any engine, tool, or directive extension, add validation scenarios under `validation/scenarios/` to verify behavior and prevent regressions; see `docs/architecture/validation.md`.
