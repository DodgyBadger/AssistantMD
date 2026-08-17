# Vault-Relative Workflow Execution Plan

## Status

Implemented, hardened, and focused validation passing.

## Goal

Allow an agent or Monty script to execute an explicitly selected workflow file
stored anywhere inside the current vault, without expanding scheduled workflow
discovery beyond `AssistantMD/Authoring/`.

This supports project-local research automation: a workflow can live beside the
library, manifest, notes, or other material it processes instead of requiring a
copy under `AssistantMD/Authoring/`.

## Current contract

- Vault and system workflow discovery is rooted in `AssistantMD/Authoring/` and
  `system/Authoring/`.
- Discovered workflow names are resolved through `WorkflowLoader` as
  `vault/name` identities.
- Scheduler, API, and `workflow_run` executions pass through
  `WorkflowGovernor`, the shared execution-task lifecycle, the per-vault lane,
  timeout handling, cancellation, rollback, activity logging, and durable run
  history.
- `workflow_run` currently resolves `workflow_name` relative to
  `AssistantMD/Authoring/`. Its `run` and `start` operations ultimately reload a
  discovered workflow by global ID.

The Authoring location is therefore both a discovery convention and an
assumption in the current load-by-ID execution path. It is not the Monty
sandbox boundary itself.

## Proposed contract

### Managed workflows

Preserve the existing `workflow_name` contract for managed workflows:

- `list` discovers only `AssistantMD/Authoring/` and system templates.
- scheduling discovers only managed workflows;
- `enable_workflow` and `disable_workflow` apply only to managed workflows;
- context-template discovery and selection remain unchanged;
- Dashboard workflow management remains based on discovered workflows.

### Ad hoc vault workflows

Add an optional `workflow_path` argument to `workflow_run` for `run` and
`start` only. The value is a vault-relative Markdown path, for example:

```text
Research/Forest Resiliency/automation/process-library.md
```

When `workflow_path` is supplied:

- resolve it relative to the current vault, never the process working
  directory or data root;
- require a `.md` file with explicit `run_type: workflow` frontmatter and one
  valid fenced Python block;
- execute it through the same governor, execution-task, timeout, cancellation,
  rollback, activity, and durable-history path as a managed workflow;
- ignore scheduling and enabled-state frontmatter for this explicit run;
- do not add the file to discovery, scheduler reconciliation, lifecycle
  operations, context selection, or the managed-workflow UI;
- record its canonical vault-relative path in task metadata, lifecycle events,
  failures, and durable run history so the executed artifact is auditable.

`workflow_name` and `workflow_path` are mutually exclusive for `run` and
`start`. Existing callers remain compatible.

## Path and execution invariants

- Resolve the current vault through the existing configured-vault path helper.
- Reject absolute paths, empty paths, traversal components, non-Markdown files,
  directories, missing files, and paths that resolve outside the current vault.
- Resolve symlinks before the containment check; a symlink may not escape the
  vault.
- Do not infer executability merely from the presence of a Python fence. Require
  explicit `run_type: workflow` to avoid executing ordinary research notes that
  contain code examples.
- Preserve the current tool instruction that the agent summarizes the workflow
  and obtains confirmation before execution.
- Preserve vault-scoped serialization and the configured workflow timeout.
- Use a stable display/history identity derived from the canonical
  vault-relative path, while keeping the path as a separate structured field.
  Do not overload discovered workflow names or register the ad hoc workflow in
  `WorkflowLoader`.

## Implementation shape

### 1. Introduce an explicit execution target

Add a small workflow execution-target value object containing:

- vault name;
- stable workflow ID/display label;
- optional managed workflow name;
- optional canonical vault-relative path;
- resolved file path.

Keep resolution separate from execution. Managed targets continue to resolve
through `WorkflowLoader`; ad hoc targets resolve through the vault-contained
path resolver and authoring parser.

### 2. Generalize execution without bypassing governance

Extend `WorkflowGovernor.execute_workflow()` and `start_workflow()` to accept an
already validated execution target, or add parallel target-based entry points
that immediately converge on the existing governed execution body.

The target-based runner should call `run_authoring_template()` directly for an
ad hoc file after validation. It must not create a second execution pipeline or
call the authoring service directly from the tool outside the governor.

Managed scheduler and API callers should retain their current load-by-global-ID
behavior.

### 3. Extend the tool contract

Update `core/tools/workflow_run.py` to:

- accept `workflow_path`;
- validate mutual exclusivity and operation support;
- resolve and validate ad hoc targets;
- dispatch blocking and background runs through the governed target path;
- keep `list`, `status`, `cancel`, enable, and disable behavior stable;
- explain in the one-line description and detailed tool documentation that
  paths are explicit, vault-relative, unscheduled workflows.

The same tool remains callable from Monty, satisfying deterministic scripted
use without another API surface.

### 4. Preserve observability

Extend task metadata and `workflow_runs.db` only if needed to store the
vault-relative source path as a distinct field. If a database column is added,
use the managed system migration path and include backup/migration validation.

Activity and failure records should identify both the stable workflow ID and
source path. The Dashboard may show these runs in execution history, but should
not present them as discovered or schedulable workflows.

### 5. Update current-contract documentation

Update:

- `docs/tools/workflow_run.md`;
- `docs/use/authoring.md`;
- `docs/architecture/authoring-engine.md`;
- `docs/architecture/llm-tools.md`;
- `docs/architecture/execution-tasks.md` if target metadata changes.

Add an ADR only after accepting the contract, because this deliberately
separates the managed workflow catalog from the executable authoring-file
location.

## Validation target

Extend `validation/scenarios/integration/core/workflow_run_async.py` or add a
focused `vault_relative_workflow_run.py` scenario proving:

- a nested vault-relative workflow outside `AssistantMD/Authoring/` can run and
  start through `workflow_run`;
- its result, task metadata, activity, cancellation/rollback behavior, and
  durable history identify the source path;
- it does not appear in `list`, scheduler jobs, or lifecycle operations;
- absolute paths, traversal, symlink escapes, non-Markdown files, missing files,
  context templates, and ordinary Markdown with a Python example are rejected;
- managed `workflow_name` execution remains unchanged;
- supplying both `workflow_name` and `workflow_path` fails clearly.

Maintainers should run the full validation suite after the focused scenario and
agent-owned static checks pass.

## Risks and tradeoffs

- The feature makes executable automation less visually centralized. Explicit
  frontmatter, confirmation, source-path logging, and non-discovery keep that
  cost bounded.
- Any vault file explicitly selected by an authorized agent can become an
  execution source. This does not add host-Python authority—the Monty sandbox
  and host capabilities remain unchanged—but it increases the number of places
  executable code may be stored.
- Durable identity needs care when a project-local workflow is renamed. History
  should retain the path used for each run rather than pretending renamed files
  are the same managed workflow.
- Generalizing `WorkflowLoader` to scan the entire vault would increase startup
  cost, accidental discovery, name collisions, and scheduling ambiguity. This
  plan intentionally avoids that design.

## Non-goals

- Whole-vault workflow discovery.
- Scheduling workflows stored outside `AssistantMD/Authoring/`.
- Enabling or disabling ad hoc workflow paths.
- Using arbitrary vault paths for context templates.
- Executing DOCX, PDF, or other non-Markdown files as workflows.
- Changing Monty capabilities or sandbox permissions.

## Next step

Request the maintainer-owned full validation suite before release.
