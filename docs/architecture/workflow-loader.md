# Workflow Loader Subsystem

Workflow Loader discovers workflow files, parses/validates frontmatter, and resolves execution engines.

## Primary code

- `core/workflow/loader.py`
- `core/workflow/parser.py`
- `core/workflow/definition.py`

## Responsibilities

- Discover vaults and workflow files (`AssistantMD/Workflows`, one folder level deep).
- Parse workflow files and validate configuration.
- Resolve schedule strings into trigger objects.
- Dynamically load workflow engine entrypoints from `workflow_engines/<name>/workflow.py`.
- Track configuration errors and loaded workflow metadata.

## Engine resolution

Workflow frontmatter includes:

```yaml
workflow_engine: step
```

Loader imports:

- `workflow_engines.<engine>.workflow`

And expects:

- `async def run_workflow(job_args: dict, **kwargs)`

## Runtime interaction

- Runtime bootstrap creates `RuntimeContext.workflow_loader`.
- Scheduler sync (`setup_scheduler_jobs`) reloads workflow definitions and reconciles scheduler jobs.
- Manual run paths can load a specific workflow by `vault/name`.
