---
run_type: context
description: Workflow-focused assistant template for creating and modifying constrained-Python workflows.
---
```python
"""Workflow authoring assistant: pass history with workflow-authoring behavioral instructions."""

import json

history_result = await call_tool(
    name="memory_ops",
    arguments={"operation": "get_history", "scope": "session", "limit": "all"},
)
history = [
    {"role": item["role"], "content": item["content"]}
    for item in json.loads(history_result.output)["items"]
]

await assemble_context(
    history=history,
    instructions=(
        "Keep answers concise unless asked for more detail.\n\n"
        "When authoring workflows:\n"
        "- Treat `AssistantMD/Authoring/` as the canonical home for workflow and context templates.\n"
        "- Inspect the current runtime contract before guessing capability signatures or return shapes.\n"
        "- Use `__virtual_docs__/use/workflow_authoring.md` for workflow file shape and frontmatter guidance.\n"
        "- Run compile-only workflow testing before execution when validating a new or changed workflow.\n"
        "- Keep workflow changes small, testable, and easy to review.\n"
        "- Do not rely on existing workflow examples as the contract."
    ),
)
```
