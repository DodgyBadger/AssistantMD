# `diff_file`

## Purpose

Compare a vault file's current content against the latest retained previous snapshot for the same path.

## Parameters

- `path`: vault-relative file path to diff

## Examples

```python
diff_file(path="notes/meeting_notes.md")
```

In scripted Monty flows:

```python
diff = await diff_file(path="notes/meeting_notes.md")
if diff.metadata.get("available") and diff.metadata.get("has_changes"):
    await file_ops_safe(
        operation="write",
        path="notes/meeting_notes.diff.md",
        content=diff.return_value,
    )
```

## Output Shape

Returns a unified diff when a retained previous snapshot exists.

In scripted Monty flows, direct calls return an object with `return_value`, `metadata`, `content`, and `items`:

- `return_value`: unified diff text when changes are available, a no-change message, or unavailable guidance
- `metadata.status`: `completed`, `unavailable`, or `error`
- `metadata.available`: whether a retained previous snapshot was resolved
- `metadata.has_changes`: whether the unified diff contains changes
- `metadata.path`: normalized vault-relative path
- `metadata.reason`: structured unavailable or error reason when present
- `metadata.diff`: structured diff metadata, including baseline and current hashes when available

When no retained previous snapshot can be resolved, `metadata.status` is `unavailable`, `metadata.reason` is `previous_snapshot_unavailable`, and `return_value` suggests increasing `task_snapshot_retention_days`.

## Notes

- The baseline is the latest retained pre-mutation snapshot recorded by vault state for that path.
- Snapshot retention is controlled by `task_snapshot_retention_days`.
- This tool does not select arbitrary historical versions.
