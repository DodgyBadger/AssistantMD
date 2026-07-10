# 0023 - Split Vault Reads From Reviewed Vault Mutations

## Status

Accepted.

## Context

AssistantMD needs one consistent vault operation service for chat tools,
authored scripts, mutation auditing, snapshots, and inline collaborative editing.
The previous model-facing split between safe and unsafe operations mixed reads
with some writes and separated writes according to perceived risk. That boundary
did not align with deferred tool review, which is applied at the tool-call level.

## Decision

Expose two model-facing tools:

- `file_read` performs `read`, `list`, `search`, and `frontmatter` operations.
- `file_write` performs `write`, `append`, `edit_line`, `replace_text`, `move`,
  `delete`, and `mkdir` operations.

Both tools are thin adapters over shared operations in
`core.vault_state.file_operations`. Mutations continue through
`core.vault_state.file_mutations` for audit, snapshots, refresh, and rollback.

Interactive chats have `normal` and `collaborative` modes. Collaborative mode
defers `file_write` through Pydantic AI tool approval and renders the deferred
call as an inline review card. `file_read` remains immediate. Workflows, context
scripts, code execution, and delegate runs do not wait for interactive review.

Tool availability is app-wide through `enabled_tools`; chat does not select a
per-turn tool subset in the UI.

## Consequences

- Read-only inspection never blocks on collaborative review.
- Every reviewed mutation executes through the same tool and vault service as a
  direct mutation.
- Multiple independent mutations use separate tool calls so collaborative
  review retains per-operation decisions and results.
- `move(overwrite=true)` represents explicit destination replacement.
- `write(overwrite=true, content="")` represents clearing a file; there is no
  separate truncate operation.
- Existing settings may retain retired tool entries, but enabled-tool resolution
  ignores retired built-in names and settings repair prunes them.
- Persisted historical tool events can still be interpreted by compatibility
  adapters without keeping the retired executable tools registered.

## Evidence

- `core/tools/file_read.py`
- `core/tools/file_write.py`
- `core/vault_state/file_operations.py`
- `core/chat/deferred_reviews.py`
- `static/js/deferred-reviews.js`
- `validation/scenarios/integration/core/file_ops_unified_tool.py`
- `validation/scenarios/integration/core/file_ops_collaborative_policy.py`
