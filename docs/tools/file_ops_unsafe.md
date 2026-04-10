# `file_ops_unsafe`

## Purpose

Modify, overwrite, truncate, move-overwrite, or delete vault files when destructive changes are explicitly needed.

## When To Use

- the user explicitly wants a destructive or overwrite-capable file operation
- you already inspected the target file with `file_ops_safe`
- you need a narrow, deliberate text replacement or deletion

## When Not To Use

- `file_ops_safe` can do the job
- you have not read and verified the file first
- the user has not clearly authorized destructive changes

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

Returns plain text success or error messages.

## Notes

- this tool does not support read, list, or search
- use `file_ops_safe` first to inspect and verify the target
- delete and truncate require explicit path confirmation
- destructive changes have no undo
