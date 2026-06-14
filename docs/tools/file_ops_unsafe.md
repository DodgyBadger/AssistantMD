# `file_ops_unsafe`

## Purpose

Modify, overwrite, truncate, move-overwrite, or delete vault files and empty directories when destructive changes are explicitly needed.

## Operations

- `edit_line`
- `replace_text`
- `delete`
- `truncate`
- `move_overwrite`

## Examples

```python
file_ops_unsafe(
    operation="edit_line",
    path="notes/todo.md",
    line_number=5,
    old_content="- [ ] draft",
    new_content="- [x] draft",
)
```

```python
file_ops_unsafe(
    operation="delete",
    path="notes/old.md",
    confirm_path="notes/old.md",
)
```

```python
file_ops_unsafe(
    operation="delete",
    path="archive/empty-folder",
    confirm_path="archive/empty-folder",
)
```

## Output Shape

Returns human-readable output plus structured metadata.

In scripted Monty flows, direct calls return an object with `return_value`, `metadata`, `content`, and `items`. Use `result.return_value` for the tool result and `result.metadata` for control flow:

- `status`: `completed`, `partial`, `not_found`, `invalid_target`, or `error`
- `operation`
- `path`
- `destination` when applicable
- `exists` when applicable
- operation-specific fields such as `line_number` or `replacement_count`
- for directory deletion, `removed_directories`, `skipped_non_empty_directories`, `removed_count`, and `skipped_count`

## Notes

- this tool does not support read, list, or search
- use `file_ops_safe` first to inspect and verify the target
- `delete` and `move_overwrite` can operate on any existing vault file, including attachments and other non-markdown files
- `delete` can also clean up directories, but only removes empty directories; it walks the requested directory bottom-up, removes empty descendants where possible, and returns non-empty directories in `skipped_non_empty_directories`
- text mutation operations are markdown-only
- delete and truncate require explicit path confirmation
- destructive changes have no undo
- in scripted Monty flows, use `result.metadata["status"]` for branching
