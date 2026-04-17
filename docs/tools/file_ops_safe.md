# `file_ops_safe`

## Purpose

Read, write, append, list, search, and move files safely within the current vault or virtual mounts.

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

Returns human-readable output plus structured metadata.

When used through `call_tool(...)`, use `result.metadata` for control flow:

- `status`: `completed`, `not_found`, `already_exists`, `invalid_target`, `unsupported`, or `error`
- `operation`: resolved operation name
- `path` / `target`
- `exists` when applicable
- operation-specific fields such as:
  - `file_count`, `directory_count`, `files`, `directories` for `list`
  - `match_count`, `matches` for `search`
  - `content_chars`, `media_mode` for `read`

Some reads may also return multimodal tool content:

- image files can be attached directly
- markdown files with embedded local images can return ordered multimodal content

## Vault Exploration Pattern

Orient before you synthesise:

1. `list` the relevant directory to get filenames and structure
2. Use `code_execution_local` with `parse_markdown` to extract frontmatter, headings, and sections without reading full content
3. Filter and select structurally, then read only what you need

Avoid broad recursive lists or searches unless the scope is already known.

## Notes

- writes are safe: no overwrite, no destructive delete, no truncation
- virtual mounts are readable but protected from write operations
- in scripted Monty flows, use `result.metadata["status"]` for branching
