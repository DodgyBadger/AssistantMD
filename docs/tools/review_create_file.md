# `review_create_file`

Create one vault file through the inline review workflow.

Use this when a chat task should create a file but the user should inspect or
edit the proposed content before it is written.

Arguments:

- `path`: vault-relative destination path.
- `content`: complete file content to write.

Behavior:

- The tool call pauses for inline review before writing.
- Approved calls create the file through the normal vault mutation path.
- Approved override args can change `path` or `content` before execution.
- Parent directories are created as needed.
- Existing files are rejected.
