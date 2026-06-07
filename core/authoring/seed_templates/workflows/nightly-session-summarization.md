---
run_type: workflow
schedule: "cron: 0 2 * * *"
enabled: false
description: Summarize chat sessions with missing or stale stored summaries.
---

## Nightly session summarization

This workflow is disabled by default. Run it manually while tuning the batch
size, then enable it when the summarization behavior looks right.

```python
"""Summarize a bounded batch of chat sessions with missing or stale summaries."""

# Editable settings
BATCH_SIZE = 5
SUMMARIZATION_MODEL = "gpt-mini"


pending = await retrieve_sessions(selection="pending_or_stale_summary", limit=BATCH_SIZE)
sessions = list(pending.items)

if not sessions:
    await finish(status="skipped", reason="no sessions pending or stale summarization")

summarized = []

for item in sessions:
    metadata = item.metadata or {}
    session_id = metadata.get("session_id", "")
    title = metadata.get("title", "")
    message_count = metadata.get("message_count", 0)
    history_revision = metadata.get("history_revision", 0)
    summary_status = metadata.get("summary_status", "")

    if not session_id:
        raise ValueError("Cannot summarize a session item without session_id")

    result = await session_ops(
        operation="summarize_session",
        session_id=session_id,
        summarization_model=SUMMARIZATION_MODEL,
    )
    summarized.append(
        {
            "session_id": session_id,
            "title": title,
            "message_count": message_count,
            "history_revision": history_revision,
            "summary_status": summary_status,
            "result": result.return_value,
        }
    )

{
    "status": "completed",
    "selected": len(sessions),
    "summarized": len(summarized),
    "batch_size": BATCH_SIZE,
    "summarization_model": SUMMARIZATION_MODEL,
}
```
