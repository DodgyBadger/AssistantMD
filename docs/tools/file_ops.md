# `file_ops`

## Purpose

Read, list, search, write, append, edit, move, delete, and create folders within
the current vault.

## Operations

- `read`
- `list`
- `search`
- `write`
- `append`
- `replace_text`
- `move`
- `delete`
- `mkdir`
- `batch`

## Parameters

- `operation`: operation name
- `path`: vault-relative file or directory path
- `content`: full content for `write`, or content to add for `append`
- `destination`: destination path for `move`
- `recursive`: recurse through subdirectories for `list`
- `search_term`: text to search for
- `old_text`: exact text to replace for `replace_text`
- `new_text`: replacement text for `replace_text`
- `count`: number of replacements for `replace_text`, default `1`
- `overwrite`: for `write`, replace existing full-file content when `true`
- `confirm_path`: required path confirmation for `delete`
- `start_line`: optional 1-indexed first line for `read`
- `line_count`: optional number of lines for `read`
- `operations`: operation objects for `batch`

## Examples

```python
file_ops(operation="list")
```

```python
file_ops(operation="read", path="notes/project.md")
```

```python
file_ops(operation="read", path="notes/project.md", start_line=1, line_count=40)
```

```python
file_ops(operation="search", path="projects", search_term="TODO")
```

```python
file_ops(operation="write", path="notes/new.md", content="# Draft\n")
```

`write` is create-only by default. If the file already exists, it returns
`status: "already_exists"` and does not overwrite.

```python
file_ops(
    operation="write",
    path="notes/existing.md",
    content="# Replacement\n",
    overwrite=True,
)
```

Use `overwrite=True` only when the user intent to replace the full file is clear.

```python
file_ops(operation="append", path="notes/log.md", content="\n- New item")
```

```python
file_ops(
    operation="replace_text",
    path="notes/todo.md",
    old_text="- [ ] draft",
    new_text="- [x] draft",
)
```

```python
file_ops(operation="move", path="Draft.md", destination="Archive/Draft.md")
```

```python
file_ops(operation="delete", path="Scratch.md", confirm_path="Scratch.md")
```

```python
file_ops(
    operation="batch",
    operations=[
        {"operation": "write", "path": "notes/a.md", "content": "# A\n"},
        {"operation": "write", "path": "notes/b.md", "content": "# B\n"},
        {"operation": "move", "path": "notes/b.md", "destination": "archive/b.md"},
    ],
)
```

`batch` runs operations sequentially and reports one result row for each item. It
does not roll back earlier successful operations if a later row fails.

## Output Shape

Returns human-readable output plus structured metadata.

In scripted Monty flows, direct calls return an object with `return_value`,
`metadata`, `content`, and `items`. Use `result.return_value` for the tool result
and `result.metadata` for control flow.

Common metadata fields:

- `tool_name`: `file_ops`
- `status`: `completed`, `not_found`, `already_exists`, `invalid_target`,
  `unsupported`, `partial`, or `error`
- `operation`
- `path`
- `destination` when applicable
- `exists` when applicable
- `error_type` when applicable
- operation-specific fields such as `replacement_count`, `content_chars`,
  `line_count`, `lines_returned`, `files`, `directories`, or mutation ids
- `batch` adds `total`, `completed`, `failed`, and `results`

## Notes

- Paths are vault-relative.
- Read/list/search support virtual read-only mounts such as `__virtual_docs__`.
- Mutating operations cannot write to virtual mounts.
- `write`, `append`, `replace_text`, and `mkdir` are markdown/text oriented.
- `move` and `delete` can operate on supported vault files and directories as
  implemented by the underlying mutation helpers.
- Use `replace_text` for exact in-file edits; use `write(overwrite=True)` only
  for full-file replacement.
- Use `read` with `start_line` and `line_count` instead of a separate `head`
  operation.
