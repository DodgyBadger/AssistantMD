---
run_type: context
description: Default template for regular chat. Passes full history. Loads soul.md, playbooks, user.md, and skill catalog if present.
---
```python
"""Default chat context: pass history, inject soul.md, playbooks, user context, and skills catalog if present."""

DEFAULT_PLAYBOOK = (
    "## Vault Work Policy\n"
    "Treat the active vault as the user's source of truth for their files, "
    "notes, drafts, and project context.\n\n"
    "When a workspace playbook is loaded, merge it with this vault-level "
    "guidance. Treat workspace guidance as more specific when the two directly "
    "conflict."
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
        "- Use active voice. Avoid contrast / framing-by-negation. \n"
        "- Prefer tool-grounded answers when current facts or user files matter."
    )
)

DEFAULT_USER_NOTES_FILE = "AssistantMD/user.md"
DEFAULT_USER_NOTES_CHAR_LIMIT = 6000


def split_parent_filename(path):
    parts = path.rsplit("/", 1)
    if len(parts) == 1:
        return ".", parts[0]
    return parts[0] or ".", parts[1]


async def read_convention_file(path):
    exact_result = await file_ops_safe(operation="read", path=path)
    if exact_result.metadata.get("status") == "completed":
        return path, exact_result

    parent, filename = split_parent_filename(path)
    listing = await file_ops_safe(operation="list", path=parent, include_all=True)
    if listing.metadata.get("status") != "completed":
        return path, exact_result

    filename_lower = filename.lower()
    matches = []
    for candidate in listing.metadata.get("files", []):
        candidate_name = candidate.rsplit("/", 1)[-1]
        if candidate_name.lower() == filename_lower:
            matches.append(candidate)

    if len(matches) != 1:
        return path, exact_result

    matched_path = matches[0]
    matched_result = await file_ops_safe(operation="read", path=matched_path)
    if matched_result.metadata.get("status") == "completed":
        return matched_path, matched_result
    return path, exact_result


def bounded_text(value, max_chars):
    text = value.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n\n[User notes truncated by default context script.]"


def frontmatter_value(result, key, default_value):
    if result.metadata.get("status") != "completed":
        return default_value
    items = result.metadata.get("items", [])
    if not items:
        return default_value
    frontmatter = items[0].get("frontmatter", {})
    value = frontmatter.get(key)
    return default_value if value in (None, "") else value


def parse_positive_int(value, default_value):
    try:
        parsed = int(value)
    except Exception:
        return default_value
    return parsed if parsed > 0 else default_value


playbook_path, playbook_result = await read_convention_file("AssistantMD/playbook.md")
playbook_instructions = (
    playbook_result.return_value.strip()
    if playbook_result.metadata.get("status") == "completed"
    else DEFAULT_PLAYBOOK
)

workspace_playbook_instructions = ""
if workspace.exists:
    workspace_playbook_path = f"{workspace.path}/playbook.md"
    workspace_playbook_path, workspace_playbook_result = await read_convention_file(workspace_playbook_path)
    if workspace_playbook_result.metadata.get("status") == "completed":
        workspace_playbook_text = workspace_playbook_result.return_value
        if workspace_playbook_text.strip():
            workspace_playbook_instructions = (
                "## Workspace Playbook\n"
                f"The following workspace-specific playbook was loaded from `{workspace_playbook_path}`. "
                "Treat it as more specific than the vault-level playbook when the two directly conflict.\n\n"
                + bounded_text(workspace_playbook_text, 6000)
            )


USER_NOTES_skill_result = await file_ops_safe(
    operation="frontmatter",
    path="AssistantMD/Skills/save_user_note.md",
    keys="USER_NOTES_file,USER_NOTES_char_limit",
)
USER_NOTES_file = frontmatter_value(USER_NOTES_skill_result, "USER_NOTES_file", DEFAULT_USER_NOTES_FILE)
USER_NOTES_char_limit = parse_positive_int(
    frontmatter_value(USER_NOTES_skill_result, "USER_NOTES_char_limit", DEFAULT_USER_NOTES_CHAR_LIMIT),
    DEFAULT_USER_NOTES_CHAR_LIMIT,
)

USER_NOTES_result = await file_ops_safe(operation="read", path=USER_NOTES_file)
USER_NOTES_instructions = ""
if USER_NOTES_result.metadata.get("status") == "completed":
    USER_NOTES_text = USER_NOTES_result.return_value
    if USER_NOTES_text.strip():
        USER_NOTES_instructions = (
            "## User Notes\n"
            f"The following user-maintained notes were loaded from `{USER_NOTES_file}`. "
            "Treat them as editable context, not hidden authority.\n\n"
            + bounded_text(USER_NOTES_text, USER_NOTES_char_limit)
        )

workspace_instructions = ""
if workspace.exists:
    workspace_overview_path = f"{workspace.path}/README.md"
    workspace_overview_path, workspace_overview_result = await read_convention_file(workspace_overview_path)
    if workspace_overview_result.metadata.get("status") == "completed":
        workspace_overview_text = workspace_overview_result.return_value
        if workspace_overview_text.strip():
            workspace_instructions = (
                "## Workspace\n"
                f"The current chat workspace is `{workspace.path}`. "
                f"The following workspace README was loaded from `{workspace_overview_path}`.\n\n"
                + bounded_text(workspace_overview_text, 6000)
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
if workspace_playbook_instructions:
    instructions += "\n\n" + workspace_playbook_instructions
if USER_NOTES_instructions:
    instructions += "\n\n" + USER_NOTES_instructions
if workspace_instructions:
    instructions += "\n\n" + workspace_instructions
if skills_lines:
    instructions += (
        "\n\n## Skills\n"
        "The following skills are available. When a skill seems relevant to the user's request, "
        "read the full skill file before responding. For explicit requests to remember, save, "
        "or persist facts for future chats, use the Save User Note skill.\n"
        + "\n".join(skills_lines)
    )

await assemble_context(history=history, instructions=instructions)
```
