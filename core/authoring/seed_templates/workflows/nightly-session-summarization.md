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
failed = []

for item in sessions:
    metadata = item.metadata or {}
    session_id = metadata.get("session_id", "")
    title = metadata.get("title", "")
    message_count = metadata.get("message_count", 0)
    summary_status = metadata.get("summary_status", "")

    if not session_id:
        failed.append({"session_id": "", "title": title, "error": "missing session_id"})
        continue

    try:
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
                "summary_status": summary_status,
                "result": result.return_value,
            }
        )
    except Exception as exc:
        failed.append(
            {
                "session_id": session_id,
                "title": title,
                "message_count": message_count,
                "summary_status": summary_status,
                "error": str(exc),
            }
        )

{
    "status": "completed" if not failed else "completed_with_errors",
    "selected": len(sessions),
    "summarized": len(summarized),
    "failed": len(failed),
    "batch_size": BATCH_SIZE,
    "summarization_model": SUMMARIZATION_MODEL,
    "failures": failed,
}
```
