# `file_ops_unsafe`

## Purpose

Modify, overwrite, truncate, move-overwrite, or delete vault files when destructive changes are explicitly needed.

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

## Output Shape

Returns human-readable output plus structured metadata.

In scripted Monty flows, direct calls return an object with `output`, `metadata`, `content`, and `items`. Use `result.metadata` for control flow:

- `status`: `completed`, `not_found`, `invalid_target`, or `error`
- `operation`
- `path`
- `destination` when applicable
- `exists` when applicable
- operation-specific fields such as `line_number` or `replacement_count`

## Notes

- this tool does not support read, list, or search
- use `file_ops_safe` first to inspect and verify the target
- delete and truncate require explicit path confirmation
- destructive changes have no undo
- in scripted Monty flows, use `result.metadata["status"]` for branching
