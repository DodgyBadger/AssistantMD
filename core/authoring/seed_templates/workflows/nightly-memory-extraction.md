---
run_type: workflow
schedule: "cron: 0 2 * * *"
enabled: false
description: Extract session memory for chat sessions with missing or stale derived memory.
---

## Nightly memory extraction

This workflow is disabled by default. Run it manually while tuning the batch
size, then enable it when the extraction behavior looks right.

```python
"""Extract memory for a bounded batch of chat sessions with missing or stale memory."""

# Editable settings
BATCH_SIZE = 5
EXTRACTION_MODEL = "gpt-mini"


pending = await retrieve_sessions(selection="pending_or_stale_memory", limit=BATCH_SIZE)
sessions = list(pending.items)

if not sessions:
    await finish(status="skipped", reason="no sessions pending or stale memory extraction")

extracted = []
failed = []

for item in sessions:
    metadata = item.metadata or {}
    session_id = metadata.get("session_id", "")
    title = metadata.get("title", "")
    message_count = metadata.get("message_count", 0)
    memory_status = metadata.get("memory_status", "")

    if not session_id:
        failed.append({"session_id": "", "title": title, "error": "missing session_id"})
        continue

    try:
        result = await memory_ops(
            operation="extract_session_memory",
            session_id=session_id,
            extraction_model=EXTRACTION_MODEL,
        )
        extracted.append(
            {
                "session_id": session_id,
                "title": title,
                "message_count": message_count,
                "memory_status": memory_status,
                "result": result.return_value,
            }
        )
    except Exception as exc:
        failed.append(
            {
                "session_id": session_id,
                "title": title,
                "message_count": message_count,
                "memory_status": memory_status,
                "error": str(exc),
            }
        )

{
    "status": "completed" if not failed else "completed_with_errors",
    "selected": len(sessions),
    "extracted": len(extracted),
    "failed": len(failed),
    "batch_size": BATCH_SIZE,
    "extraction_model": EXTRACTION_MODEL,
    "failures": failed,
}
```
