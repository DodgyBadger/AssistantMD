---
run_type: context
description: Default template for regular chat. Passes full history. Loads soul.md instructions and skill catalog if present.
---
```python
"""Default chat context: pass history, inject soul.md instructions and skills catalog if present."""

import json

history_result = await call_tool(
    name="memory_ops",
    arguments={"operation": "get_history", "scope": "session", "limit": "all"},
)
history = [
    {"role": item["role"], "content": item["content"]}
    for item in json.loads(history_result.output)["items"]
]

soul_result = await call_tool(
    name="file_ops_safe",
    arguments={"operation": "read", "target": "AssistantMD/soul.md"},
)
soul_instructions = (
    soul_result.output.strip()
    if soul_result.metadata.get("status") == "completed"
    else (
        "Default stance: concise and curious. Act as a guide, not a sage.\n"
        "- Start with the minimum useful answer.\n"
        "- Ask brief clarifying questions when intent, scope, or constraints are unclear.\n"
        "- Avoid long explanations until the user asks for depth.\n"
        "- Prefer next-step guidance over broad monologues.\n"
        "- Prefer tool-grounded answers when current facts or user files matter."
    )
)

skills_result = await call_tool(
    name="file_ops_safe",
    arguments={"operation": "frontmatter", "path": "AssistantMD/Skills", "keys": "name,description"},
)
skills_lines = []
if skills_result.metadata.get("status") == "completed":
    for item in skills_result.metadata.get("items", []):
        fm = item.get("frontmatter", {})
        name = fm.get("name") or item["path"].rsplit("/", 1)[-1].replace(".md", "")
        description = fm.get("description", "")
        path = item["path"]
        skills_lines.append(f"- **{name}** (`{path}`): {description}" if description else f"- **{name}** (`{path}`)")

instructions = soul_instructions
if skills_lines:
    instructions += (
        "\n\n## Skills\n"
        "The following skills are available. When a skill seems relevant to the user's request, "
        "read the full skill file before responding.\n"
        + "\n".join(skills_lines)
    )

await assemble_context(history=history, instructions=instructions)
```
