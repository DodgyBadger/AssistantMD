# Chat Task Execution Redesign Plan

Status: superseded by `CHAT_TASK_API_RETIREMENT_PLAN.md`.

The implemented contract is task-owned chat execution:

- Submit chat turns with `POST /api/chat/tasks`.
- Observe deltas and terminal events with `GET /api/chat/tasks/{task_id}/events`.
- Inspect or cancel work with `/api/tasks/{task_id}` and `/api/tasks/{task_id}/cancel`.
- Cancel the active turn for a session with `/api/chat/sessions/{session_id}/cancel`.

The current architecture is documented in:

- `docs/architecture/chat-sessions.md`
- `docs/architecture/execution-tasks.md`

Future work for additional chat surfaces should adapt to this task contract
rather than adding another chat execution path.
