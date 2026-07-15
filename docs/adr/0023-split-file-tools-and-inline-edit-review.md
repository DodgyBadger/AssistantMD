# 0023 - Split Vault Reads From Reviewed Vault Mutations

## Status

Accepted.

## Context

AssistantMD needs one consistent vault operation service for chat tools,
authored scripts, mutation auditing, snapshots, and inline editing.
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
File mutations share a process-local vault hierarchy lock while directory
hierarchy changes hold it exclusively. Mutations targeting the same resolved
path are serialized in that shared layer; read-modify-write operations hold the
same locks from read through persistence.

Interactive chats have `normal` and `inline_edit` modes. Inline edit mode
defers `file_write` through Pydantic AI tool approval and renders the deferred
call as an inline review card. `file_read` remains immediate. Workflows, context
scripts, code execution, and delegate runs do not wait for interactive review.

Deferred review is a durable pause in the chat task lifecycle. A pending review
is claimed atomically, its resumed task uses the same per-session execution gate
as ordinary chat turns, and the review records `completed`, `failed`, or
`cancelled` when that task terminates. Destructive operations capture target
existence and content hashes when the card is created; approval is rejected if
the reviewed target changed before submission. Review overrides may edit
operation content or a move destination, but cannot change the operation target
or overwrite policy.

Automatic task rollback, explicit activity rollback, and revision restoration
share the same exact-file restoration primitive. It validates expected current
states and retained restore content under the mutation locks, compensates any
partially applied filesystem changes, and only reports success after manifest
refresh and required durable finalization complete.

Tool availability is app-wide through `enabled_tools`; chat does not select a
per-turn tool subset in the UI.

## Consequences

- Read-only inspection never blocks on inline edit review.
- Every reviewed mutation executes through the same tool and vault service as a
  direct mutation.
- Multiple independent mutations use separate tool calls so inline edit
  review retains per-operation decisions and results.
- `move(overwrite=true)` represents explicit destination replacement.
- `write(overwrite=true, content="")` represents clearing a file; there is no
  separate truncate operation.
- Existing settings may retain retired tool entries, but enabled-tool resolution
  ignores retired built-in names and settings repair prunes them.
- Persisted historical tool events can still be interpreted by compatibility
  adapters without keeping the retired executable tools registered.
- Historical edit-proposal artifacts remain readable for old chat cards, but
  their former apply, deny, and review paths are not executable.

## Evidence

- `core/tools/file_read.py`
- `core/tools/file_write.py`
- `core/vault_state/file_operations.py`
- `core/chat/deferred_reviews.py`
- `static/js/deferred-reviews.js`
- `validation/scenarios/integration/core/file_ops_unified_tool.py`
- `validation/scenarios/integration/core/file_ops_inline_edit_policy.py`
