# Workflow Loader Subsystem

Workflow Loader discovers workflow files and parses/validates frontmatter.

## Primary code

- `core/workflow/loader.py`
- `core/workflow/parser.py`
- `core/workflow/definition.py`

## Responsibilities

- Discover vaults and workflow files (`AssistantMD/Workflows`, one folder level deep).
- Parse workflow files and validate configuration.
- Resolve schedule strings into trigger objects.
- Track configuration errors and loaded workflow metadata.

## Runtime interaction

- Runtime bootstrap creates `RuntimeContext.workflow_loader`.
- Scheduler sync (`setup_scheduler_jobs`) reloads workflow definitions and reconciles scheduler jobs.
- Manual run paths can load a specific workflow by `vault/name`.
