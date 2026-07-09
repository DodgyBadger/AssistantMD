# `file_write`

## Purpose

Create, append, edit, move, delete, create folders, and batch mutate files in the
current vault.

## Operations

- `write`
- `append`
- `replace_text`
- `move`
- `delete`
- `mkdir`
- `batch`

## Examples

```python
file_write(operation="write", path="notes/new.md", content="# Draft\n")
```

`write` is create-only by default. If the file already exists, it returns
`status: "already_exists"` and does not overwrite.

```python
file_write(
    operation="write",
    path="notes/existing.md",
    content="# Replacement\n",
    overwrite=True,
)
```

Use `overwrite=True` only when the user intent to replace the full file is clear.

```python
file_write(operation="append", path="notes/log.md", content="\n- New item")
```

```python
file_write(
    operation="replace_text",
    path="notes/todo.md",
    old_text="- [ ] draft",
    new_text="- [x] draft",
)
```

```python
file_write(operation="move", path="Draft.md", destination="Archive/Draft.md")
```

```python
file_write(operation="delete", path="Scratch.md", confirm_path="Scratch.md")
```

```python
file_write(
    operation="batch",
    operations=[
        {"operation": "write", "path": "notes/a.md", "content": "# A\n"},
        {"operation": "write", "path": "notes/b.md", "content": "# B\n"},
        {"operation": "move", "path": "notes/b.md", "destination": "archive/b.md"},
    ],
)
```

## Batch Rules

`batch` is for mutations only. It accepts `write`, `append`, `replace_text`,
`move`, `delete`, and `mkdir` rows. It rejects `read`, `list`, `search`, and
nested `batch` rows before executing anything.

Batch execution is sequential and non-transactional. It does not roll back
earlier successful rows if a later row fails.

## Notes

- Paths are vault-relative.
- Mutating operations cannot write to virtual mounts.
- Use `replace_text` for exact in-file edits.
- Use `file_read` before calling `file_write` when you need to inspect context.
