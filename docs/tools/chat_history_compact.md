# chat_history_compact

Check or compact the current chat session history.

Use `operation="status"` to inspect the current message and token estimate. Use
`operation="compact"` only after the user has explicitly approved compaction.

Parameters:

- `operation`: `status` or `compact`
- `focus`: optional user guidance for what the compaction summary should preserve

The compact operation records a replay checkpoint so default future history
starts with a system-maintained summary plus recent raw turns.

## Common Calls

Check whether the current session is ready for compaction:

```json
{"operation": "status"}
```

Compact the current session after explicit user approval:

```json
{
  "operation": "compact",
  "focus": "Preserve current decisions, open questions, and files changed."
}
```
