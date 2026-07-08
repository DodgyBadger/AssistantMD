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

Each edit requires:

- `path`: vault-relative path to an existing file.
- `original_text`: exact current text to replace. It must match exactly once.
- `replacement_text`: proposed replacement text.
- `rationale`: optional short explanation shown with the edit.

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
