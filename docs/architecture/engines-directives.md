# Engines + Directives Subsystem

This subsystem defines how workflows execute and how markdown control primitives are interpreted.

## Primary code

- `workflow_engines/`
- `core/directives/`
- `core/workflow/parser.py`
- `core/core_services.py`

## Responsibilities

- Workflow engines orchestrate execution (`run_workflow`).
- Directives parse/validate/transform `@directive` values into structured outputs.
- Engine code decides how directive outputs are used in orchestration.
- Built-in directives are registered centrally; custom directives can be runtime-registered.

## Built-in engine

- Current built-in workflow engine: `workflow_engines/step/workflow.py`
- Workflow files choose engine via frontmatter `workflow_engine`.

## Directive boundary

- Directive processors do not run workflow control flow themselves.
- They return primitives that engines consume (inputs/outputs/routing/tool/model config, etc.).

## Extensibility

For implementation guidance and registration options:

- `docs/architecture/extending.md`
