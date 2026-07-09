# `file_read`

## Purpose

Read, list, and search files in the current vault.

## Operations

- `read`
- `list`
- `search`

## Examples

```python
file_read(operation="list")
```

```python
file_read(operation="list", path="projects", recursive=True)
```

```python
file_read(operation="read", path="notes/project.md")
```

```python
file_read(operation="read", path="notes/project.md", start_line=1, line_count=40)
```

```python
file_read(operation="search", path="projects", search_term="TODO")
```

## Notes

- Paths are vault-relative.
- Use `read` with `start_line` and `line_count` instead of a separate `head`
  operation.
- Use `file_write` for create, edit, move, delete, mkdir, and batch operations.
