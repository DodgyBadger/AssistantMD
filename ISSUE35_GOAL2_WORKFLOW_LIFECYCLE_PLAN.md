# Issue 35 - Goal 2 Plan: `workflow_run` Lifecycle Operations

## Scope
Extend `workflow_run` with explicit lifecycle operations:
- `enable_workflow`
- `disable_workflow`

Operations must target workflows by explicit name/id, be idempotent, and produce structured status results. This applies to tool usage in workflow runs and chat contexts.
Tool name remains `workflow_run` for this issue (no rename/migration in this slice).

## Validation-First Contract

### User-visible artifacts
- `workflow_run(operation="enable_workflow", workflow_name="...")` enables a disabled workflow.
- `workflow_run(operation="disable_workflow", workflow_name="...")` disables an enabled workflow.
- Calling enable on already enabled and disable on already disabled returns idempotent statuses, not errors.
- Unknown target returns structured `not_found` result.
- Scheduler state reflects lifecycle changes after operation.

### Internal artifacts
- Existing scheduler synchronization behavior (`job_synced` events) remains stable.
- Add lifecycle audit events at decision boundaries only (no noisy instrumentation).

### Non-negotiable invariants
- Operations are non-destructive (only toggle `enabled` in workflow frontmatter).
- Must not modify unrelated frontmatter keys/content.
- Targeting must be explicit and deterministic (no fuzzy matching).
- Path resolution must enforce vault workflow root boundaries after symlink resolution (`realpath`).

## API/Tool Behavior Design

### `workflow_run` operations
- Existing:
  - `list`
  - `run`
- New:
  - `enable_workflow`
  - `disable_workflow`

### Targeting rules
- Accept explicit `workflow_name` in vault-relative form (`daily` or `folder/daily`).
- Resolve to `global_id = "{vault}/{workflow_name}"`.
- Reuse existing invalid-name/path traversal checks.
- Primary LLM path is list -> action:
  - `workflow_run(operation="list")` returns canonical names
  - LLM reuses returned `workflow_name` for enable/disable.
- Accept `AssistantMD/Workflows/...(.md)` as input convenience and normalize to canonical `workflow_name`.
- Reject absolute/runtime filesystem paths (especially `/app/data/...`) as invalid input.

### Idempotent structured statuses
- `enable_workflow` results:
  - `enabled_now`
  - `already_enabled`
  - `not_found`
- `disable_workflow` results:
  - `disabled_now`
  - `already_disabled`
  - `not_found`

### Tool response format
- Keep tool output human-readable but structured and parseable.
- Include at least:
  - `success`
  - `operation`
  - `global_id` (or attempted target)
  - `status` (from enum above)
  - `message`

## Implementation Strategy

1. Add scenario assertions first (failing contract)
- Extend/create integration scenario(s) under `validation/scenarios/integration/core/` to verify:
  - enable disabled workflow -> `enabled_now`
  - enable again -> `already_enabled`
  - disable enabled workflow -> `disabled_now`
  - disable again -> `already_disabled`
  - unknown workflow -> `not_found`
  - scheduler sync evidence after state change (`job_synced` create/remove as appropriate)

2. Add lifecycle operation plumbing in `workflow_run` tool
- Update operation parsing in `core/tools/workflow_run.py`.
- Route new operations to shared lifecycle handler(s).
- Keep existing `list`/`run` behavior unchanged.

2a. Tighten workflow name normalization/validation
- Accept canonical names (`daily`, `ops/nightly`).
- Normalize `AssistantMD/Workflows/...` prefix and optional `.md` suffix.
- Reject runtime-rooted inputs (`/app/data/...`), absolute paths, and parent traversal (`..`).
- Require exact canonical match (no fuzzy/basename-only matching).
- Resolve target path and workflow root via `realpath`; reject any path that escapes root.
- Reject symlink escape routes (and optionally symlinked workflow files if needed for stricter posture).

3. Implement workflow state mutation helper
- Add helper to update only `enabled` in YAML frontmatter for target workflow file.
- Preserve other frontmatter values and body content.
- Ensure file write is atomic/safe (write temp + replace, or equivalent existing pattern).

4. Reload + scheduler sync after mutation
- Trigger runtime workflow reload and scheduler synchronization after enable/disable.
- Ensure final state returned reflects post-reload truth.

5. Add lifecycle audit/history events
- Emit minimal validation events, e.g.:
  - `workflow_lifecycle_changed` (`operation`, `workflow_id`, `status`, `enabled_before`, `enabled_after`)
  - optional `workflow_lifecycle_noop` for idempotent path (or reuse same event with noop status)
- Keep event schema stable and behavior-oriented.

6. Error handling and UX
- Invalid target format -> actionable message.
- Not found -> structured `not_found` status (not exception stack text).
- Unexpected runtime errors -> structured failure response with short reason.
- Security boundary error:
  - Inputs containing runtime filesystem roots (`/app/data/...`) are rejected explicitly.
  - Guidance should direct callers to use list output and vault-internal `workflow_name`.

7. Docs update
- Update `workflow_run` instructions and user reference:
  - new operations and examples
  - status semantics
  - idempotency behavior
  - naming contract:
    - `workflow_name` is relative to `AssistantMD/Workflows` (without that prefix)
    - include subfolder segment when present (e.g. `ops/nightly`)
    - do not pass runtime filesystem roots

8. Local smoke tests
- Add fast targeted smoke tests for lifecycle toggling helper and tool-level result formatting.
- Do not run full validation suite in-agent.

9. Handoff
- Request maintainer-run full validation and iterate on failures.

## Event Contract (Goal 2)

### Event: `workflow_lifecycle_changed`
- Fires when lifecycle operation is evaluated (including idempotent/noop).
- Minimum payload keys:
  - `operation` (`enable_workflow` | `disable_workflow`)
  - `workflow_id`
  - `status` (`enabled_now` | `already_enabled` | `disabled_now` | `already_disabled` | `not_found`)
  - `enabled_before` (optional when `not_found`)
  - `enabled_after` (optional when `not_found`)

### Existing events
- `job_synced` remains source of truth for scheduler side effects.

## Validation Execution Reminder
- Per project guidance, do **not** run `python validation/run_validation.py` in-agent.
- Maintainers run full validation and share results.
