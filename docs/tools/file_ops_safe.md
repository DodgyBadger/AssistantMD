# `file_ops_safe`

## Purpose

Read, write, append, list, search, inspect frontmatter, and move files safely within the current vault or virtual mounts.

## Operations

- `list`
- `search`
- `read`
- `write`
- `append`
- `move`
- `mkdir`
- `frontmatter`
- `head`

## Parameters

- `path`: file, directory, or glob pattern (used by all operations)
- `content`: text to write or append
- `destination`: destination path for move
- `include_all`: include non-markdown and hidden files in listings
- `recursive`: recurse through subdirectories for listings
- `search_term`: text pattern to search for (search only)
- `keys`: comma-separated frontmatter keys to extract (frontmatter only)
- `limit`: number of lines to return, default 20 (head only)

## Examples

```python
file_ops_safe(operation="list")
```

```python
file_ops_safe(operation="list", path="projects")
```

```python
file_ops_safe(operation="search", path="projects", search_term="TODO")
```

```python
file_ops_safe(operation="read", path="notes/project.md")
```

```python
file_ops_safe(
    operation="write",
    path="notes/output.md",
    content="# Draft\n",
)
```

```python
file_ops_safe(operation="frontmatter", path="AssistantMD/Authoring")
```

```python
file_ops_safe(operation="frontmatter", path="AssistantMD/Skills", keys="name,description")
```

```python
file_ops_safe(operation="head", path="notes/long-file.md", limit=30)
```

## Output Shape

Returns human-readable output plus structured metadata.

In scripted Monty flows, direct calls return an object with `output`, `metadata`, `content`, and `items`. Use `result.metadata` for control flow:

- `status`: `completed`, `not_found`, `already_exists`, `invalid_target`, `unsupported`, or `error`
- `operation`: resolved operation name
- `path`
- `exists` when applicable
- operation-specific fields:
  - `file_count`, `directory_count`, `files`, `directories` for `list`
  - `match_count`, `matches` for `search`
  - `content_chars`, `media_mode` for `read`
  - `file_count`, `items` (list of `{path, frontmatter}`) for `frontmatter`
  - `lines_returned`, `limit` for `head`

## Vault Exploration Pattern

Orient before you synthesise:

1. `list` the relevant directory to get filenames and structure
2. `frontmatter` to inspect metadata across a directory without reading full content
3. `head` or `read` only what you need

Avoid broad recursive lists or searches unless the scope is already known.

## Notes

- writes are safe: no overwrite, no destructive delete, no truncation
- virtual mounts are readable but protected from write operations
- `frontmatter` returns all keys by default; pass `keys` to filter
- `head` defaults to 20 lines when `limit` is not specified
- in scripted Monty flows, use `result.metadata["status"]` for branching
