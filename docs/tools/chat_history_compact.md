# chat_history_compact

Check or compact the current chat session history.

Use `operation="status"` to inspect the current message and token estimate. Use
`operation="compact"` only after the user has explicitly approved compaction.

Parameters:

- `operation`: `status` or `compact`
- `focus`: optional user guidance for what the compaction summary should preserve
- `export_before`: optional boolean override for transcript export before rewrite

The compact operation rewrites canonical chat history into a system-maintained
summary plus recent raw turns. If an export is created, this tool reports that
fact but does not return the transcript path.
