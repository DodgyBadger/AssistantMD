---
run_type: context
description: Default template for regular chat. Passes full history. Loads soul.md instructions and skill catalog if present.
---
```python
"""Default chat context: pass history, inject soul.md instructions and skills catalog if present."""

DEFAULT_PLAYBOOK = (
    "## Vault-First Work Policy\n"
    "Treat the active vault as the user's first source of truth. Do not raise "
    "memory or vault search during greetings, setup, casual conversation, or "
    "before the user's work intent is clear. Once the user has described a "
    "concrete goal, and before using external research tools or starting "
    "substantial new research or synthesis, ask once whether they want you to "
    "first check prior work in the vault and session memory. Keep the question "
    "brief and concrete, for example: `Before I start fresh, do you want me to "
    "do a quick vault and session-memory search so we do not duplicate earlier "
    "work?`\n\n"
    "If the user agrees, call `memory_ops.search_sessions` with `mode=\"search\"`, "
    "a short natural-language `query` based on the current goal, and a small "
    "numeric `limit` such as 5. If useful, also use `file_ops_safe` to search "
    "vault files directly. Treat chat-session memory and file-search results as "
    "leads, not authority. Explain what you found, why it may matter, and let "
    "the user confirm or redirect before relying on it.\n\n"
    "Do not ask repeatedly. If the user declines, ignores the question, or the "
    "request is clearly small and self-contained, continue normally."
)

history_result = await retrieve_history(scope="session", limit="all")
history = list(history_result.items)

soul_result = await file_ops_safe(operation="read", path="AssistantMD/soul.md")
soul_instructions = (
    soul_result.return_value.strip()
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

playbook_result = await file_ops_safe(operation="read", path="AssistantMD/playbook.md")
playbook_instructions = (
    playbook_result.return_value.strip()
    if playbook_result.metadata.get("status") == "completed"
    else DEFAULT_PLAYBOOK
)

def skill_name_from_path(path):
    parts = path.split("/")
    filename = parts[-1] if parts else path
    if filename == "SKILL.md" and len(parts) >= 2:
        return parts[-2]
    return filename[:-3] if filename.endswith(".md") else filename


flat_skills_result = await file_ops_safe(
    operation="frontmatter",
    path="AssistantMD/Skills",
    keys="name,description",
)
folder_skills_result = await file_ops_safe(
    operation="frontmatter",
    path="AssistantMD/Skills/*/SKILL.md",
    keys="name,description",
)

skill_items_by_path = {}
for result in (flat_skills_result, folder_skills_result):
    if result.metadata.get("status") == "completed":
        for item in result.metadata.get("items", []):
            path = item.get("path", "")
            if path:
                skill_items_by_path[path] = item

skills_lines = []
for path, item in skill_items_by_path.items():
    fm = item.get("frontmatter", {})
    name = fm.get("name") or skill_name_from_path(path)
    description = fm.get("description", "")
    skills_lines.append(f"- **{name}** (`{path}`): {description}" if description else f"- **{name}** (`{path}`)")

instructions = soul_instructions
instructions += "\n\n" + playbook_instructions
if skills_lines:
    instructions += (
        "\n\n## Skills\n"
        "The following skills are available. When a skill seems relevant to the user's request, "
        "read the full skill file before responding.\n"
        + "\n".join(skills_lines)
    )

await assemble_context(history=history, instructions=instructions)
```
