# `propose_file_edits`

Create an interactive chat artifact for file edits that the user should review
before anything is written.

Use this tool when the user asks for suggested edits, approval gates, or
collaborative editing. Use direct file writing tools when the user has already
asked you to make a straightforward change without review.

## Parameters

- `title`: short title shown on the proposal card.
- `summary`: optional summary shown under the title.
- `edits`: list of proposed replacements.

Each edit supports:

- `operation`: `replace_text`, `create_file`, `delete_file`, or `move_file`.
  Omit it for `replace_text`.
- `path`: vault-relative path to an existing file.
- `rationale`: optional short explanation shown with the edit.

For `replace_text`, include:

- `original_text`: exact current text to replace. It must match exactly once.
- `replacement_text`: proposed replacement text.

For `create_file`, include `replacement_text`, `content`, or `initial_content`
with the proposed full file content. The path must not already exist.

For `delete_file`, include the existing `path`.

For `move_file`, include the existing source `path` and a `destination` path
that does not already exist.

## Example

```python
propose_file_edits(
    title="Update project status",
    summary="One status wording change.",
    edits=[
        {
            "path": "Projects/Alpha/README.md",
            "original_text": "Status: Draft",
            "replacement_text": "Status: Reviewed",
            "rationale": "Reflect the review completed in this chat.",
        }
    ],
)
```

Read the target file first with `file_ops_safe` when you are not certain of the
exact current text. The proposal records the file hash at creation time; applying
the proposal will fail if the file changes before the user clicks apply.

```python
propose_file_edits(
    title="Add archive note",
    edits=[
        {
            "operation": "create_file",
            "path": "Archive/Alpha.md",
            "replacement_text": "# Alpha\n\nArchived notes.\n",
            "rationale": "Create an archive landing note.",
        },
        {
            "operation": "move_file",
            "path": "Projects/Alpha/old.md",
            "destination": "Archive/Alpha/old.md",
            "rationale": "Move the old note into the archive.",
        },
    ],
)
```
