# Engines + Directives Subsystem

This subsystem defines how workflows execute and how markdown control primitives are interpreted.

## Primary code

- `core/directives/`
- `core/workflow/parser.py`
- `core/core_services.py`

## Responsibilities

- Directives parse/validate/transform `@directive` values into structured outputs.
- Built-in directives are registered centrally; custom directives can be runtime-registered.

## Directive boundary

- Directive processors do not run workflow control flow themselves.
- They return primitives that engines consume (inputs/outputs/routing/tool/model config, etc.).

## Extensibility

For implementation guidance and registration options:

- `docs/architecture/extending.md`
