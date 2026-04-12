# memory_ops

## Purpose

Read structured conversation history.

## When To Use

- use this when you need chat/session history as structured data
- use this for new history-aware flows.
- use this directly in chat or through `call_tool(...)` inside Monty

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

## Output Shape

Returns JSON with:

- `source`
- `scope`
- `session_id`
- `item_count`
- `items`

Each item includes:

- `role`
- `content`
- `session_id`
- `run_id`
- `message_type`
- `metadata`

## Notes

- when called from Monty in a chat session, the current session context is passed through automatically
