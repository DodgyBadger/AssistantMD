# memory_ops

## Purpose

Read structured conversation history.

## Arguments

- `operation`: currently only `get_history`
- `scope`: currently only `session`
- `session_id`: optional explicit session id; defaults to the active session when available
- `limit`: positive integer or `"all"`

## Examples

```python
memory_ops(operation="get_history", scope="session", limit=5)
```

```python
await call_tool(
    name="memory_ops",
    arguments={"operation": "get_history", "scope": "session", "limit": 10},
)
```

```python
import json

history_result = await call_tool(
    name="memory_ops",
    arguments={"operation": "get_history", "scope": "session", "limit": "all"},
)
history_payload = json.loads(history_result.output)

assembled = await assemble_context(
    history=[
        {"role": item["role"], "content": item["content"]}
        for item in history_payload["items"]
    ],
    instructions="Keep the answer concise.",
)
```

The result is JSON with top-level fields:

- `source`
- `scope`
- `session_id`
- `item_count`
- `items`

## Notes

- when called from Monty in a chat session, the current session context is passed through automatically
- use this directly in chat or through `call_tool(...)` inside Monty
- in Monty context templates, use `memory_ops` explicitly for conversation history
