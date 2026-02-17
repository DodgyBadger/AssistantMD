# Extending AssistantMD

Builder guide for extending AssistantMD in three places:

- Workflow engines (`workflow_engines/<name>/workflow.py`)
- Tools (`core/tools/*.py` + settings entry)
- Directives (`core/directives/*.py` + bootstrap registration)

This document is implementation-focused and maps directly to current code paths.

## Quick decision guide
- Use the existing step engine to build a new **workflow** when your logic fits a sequential pattern with file and web I/O.
- Add a new **workflow engine** when you need a specialized execution model.
- Add a **tool** when you need new runtime capabilities (e.g. API call).
- Add a **directive** when you need new control primitives in workflow/context files.

## 1) Custom workflow engines
Purpose: define how a workflow run is executed (execution model and step orchestration), not just what a single step prompts for.

### Contract

Workflow frontmatter selects the engine with:

```yaml
workflow_engine: your_engine_name
```

The loader imports:

`workflow_engines.<engine_name>.workflow`

and expects:

`async def run_workflow(job_args: dict, **kwargs)`

Relevant code:

- `core/workflow/parser.py`
- `core/workflow/loader.py`
- `workflow_engines/step/workflow.py` (reference implementation)

### Minimal scaffold

Create `workflow_engines/your_engine/workflow.py`:

```python
from core.core_services import CoreServices


async def run_workflow(job_args: dict, **kwargs):
    services = CoreServices(
        job_args["global_id"],
        _data_root=job_args["config"]["data_root"],
    )
    # Implement your execution pattern here.
```

### Practical approach

- Start by copying `workflow_engines/step/workflow.py`.
- Keep logging and error handling patterns consistent with existing engines.
- Reuse `CoreServices` and directive parsing where possible.
- Add only the minimum behavior needed for your specialized execution pattern.

### About CoreServices

`CoreServices` is a convenience wrapper, not a required framework layer.

- It bundles common workflow helpers (section loading, directive processing, agent creation, response generation, and path/state helpers) behind one interface.
- You can use it to move faster when prototyping engines.
- You can bypass it and call lower-level modules directly if your engine needs tighter control.

### Notes

- `step` is currently the only built-in engine.
- A custom engine is code-level extension, not just markdown configuration.

## 2) Custom tools
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

## 3) Custom directives
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
