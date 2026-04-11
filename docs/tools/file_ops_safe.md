# `file_ops_safe`

## Purpose

Read, write, append, list, search, and move files safely within the current vault or virtual mounts.

## When To Use

- you need to explore the vault structure
- you need to search markdown files for content
- you need non-destructive file writes
- you need to read markdown, text, or supported image files

## Operations

- `list`
- `search`
- `read`
- `write`
- `append`
- `move`
- `mkdir`

## Examples

```python
file_ops_safe(operation="list")
```

```python
file_ops_safe(operation="search", target="TODO", scope="projects")
```

```python
file_ops_safe(operation="read", target="notes/project.md")
```

```python
file_ops_safe(
    operation="write",
    target="notes/output.md",
    content="# Draft\n",
)
```

## Output Shape

Returns plain text for most operations.

Some reads may return multimodal tool content:

- image files can be attached directly
- markdown files with embedded local images can return ordered multimodal content

## Notes

- start discovery with `list`, then narrow scope
- avoid broad recursive lists and searches unless needed
- writes are safe: no overwrite, no destructive delete, no truncation
- virtual mounts are readable but protected from write operations
