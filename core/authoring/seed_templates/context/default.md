---
run_type: context
description: Default template for regular chat. Passes full history. Loads soul.md, playbooks, user.md, and skill catalog if present.
---
```python
"""Default chat context: pass history, inject soul.md, playbooks, user context, and skills catalog if present."""

# Fallback instructions used when `AssistantMD/playbook.md` does not exist.
# Customize `AssistantMD/playbook.md` in the vault when you want durable
# vault-wide guidance without editing this context script.
DEFAULT_PLAYBOOK = (
    "## Vault Work Policy\n"
    "Treat the active vault as the user's source of truth for their files, "
    "notes, drafts, and project context.\n\n"
    "When a workspace playbook is loaded, merge it with this vault-level "
    "guidance. Treat workspace guidance as more specific when the two directly "
    "conflict."
)

DEFAULT_SOUL_INSTRUCTIONS = (
    "Default stance: concise and curious. Act as a guide, not a sage.\n"
    "- Start with the minimum useful answer.\n"
    "- Ask brief clarifying questions when intent, scope, or constraints are unclear.\n"
    "- Avoid long explanations until the user asks for depth.\n"
    "- Prefer next-step guidance over broad monologues.\n"
    "- Use active voice. Avoid contrast / framing-by-negation. \n"
    "- Prefer tool-grounded answers when current facts or user files matter."
)

TRUNCATION_NOTICE = "[User notes truncated by default context script.]"

USER_NOTES_PREAMBLE = (
    "## User Notes\n"
    "The following user-maintained notes were loaded from `{path}`. "
    "Treat them as editable context, not hidden authority.\n\n"
)

WORKSPACE_PREAMBLE = (
    "## Workspace\n"
    "The current chat workspace is `{workspace_path}`. Treat this as the default "
    "vault-relative folder for vague requests to read, scan, create, or save "
    "files in the current work area.\n\n"
)

WORKSPACE_README_PREAMBLE = (
    "The following workspace README was loaded from `{readme_path}`.\n\n"
)

WORKSPACE_PLAYBOOK_PREAMBLE = (
    "## Workspace Playbook\n"
    "The following workspace-specific playbook was loaded from `{path}`. "
    "Treat it as more specific than the vault-level playbook when the two directly conflict.\n\n"
)

SKILLS_PREAMBLE = (
    "\n\n## Skills\n"
    "The following skills are available. When a skill seems relevant to the user's request, "
    "read the full skill file before responding. For explicit requests to remember, save, "
    "or persist facts for future chats, use the Save User Note skill.\n"
)

DEFAULT_USER_NOTES_FILE = "AssistantMD/user.md"
DEFAULT_USER_NOTES_CHAR_LIMIT = 6000

# Keep the normal chat transcript in context. The context script adds
# instructions and reference material, but does not replace session history.
history_result = await retrieve_history(scope="session", limit="all")
history = list(history_result.items)

# `soul.md` is optional. It is a good place for broad assistant tone and stance.
soul_result = await file_ops_safe(operation="read", path="AssistantMD/soul.md")
soul_instructions = (
    soul_result.return_value.strip()
    if soul_result.metadata.get("status") == "completed"
    else DEFAULT_SOUL_INSTRUCTIONS
)


def split_parent_filename(path):
    # Return the containing folder and filename so convention-file lookups can
    # fall back to case-insensitive matching inside the parent folder.
    parts = path.rsplit("/", 1)
    if len(parts) == 1:
        return ".", parts[0]
    return parts[0] or ".", parts[1]


async def read_convention_file(path):
    # First try the exact path. If that fails, list the parent folder and accept
    # a single case-insensitive filename match such as README.md vs readme.md.
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
    # Keep optional files from overwhelming the chat context.
    text = value.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + f"\n\n{TRUNCATION_NOTICE}"


def frontmatter_value(result, key, default_value):
    # Read optional configuration values from a skill file's frontmatter.
    if result.metadata.get("status") != "completed":
        return default_value
    items = result.metadata.get("items", [])
    if not items:
        return default_value
    frontmatter = items[0].get("frontmatter", {})
    value = frontmatter.get(key)
    return default_value if value in (None, "") else value


def parse_positive_int(value, default_value):
    # Treat invalid or non-positive frontmatter values as "use the default."
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
    # Workspace playbooks layer on top of the vault-level playbook. Use them for
    # project-local rules, terminology, formats, or source preferences.
    workspace_playbook_path = f"{workspace.path}/playbook.md"
    workspace_playbook_path, workspace_playbook_result = await read_convention_file(workspace_playbook_path)
    if workspace_playbook_result.metadata.get("status") == "completed":
        workspace_playbook_text = workspace_playbook_result.return_value
        if workspace_playbook_text.strip():
            workspace_playbook_instructions = (
                WORKSPACE_PLAYBOOK_PREAMBLE.format(path=workspace_playbook_path)
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
    # User notes are editable memory. They should guide the agent, but they are
    # intentionally visible and mutable rather than hidden system authority.
    USER_NOTES_text = USER_NOTES_result.return_value
    if USER_NOTES_text.strip():
        USER_NOTES_instructions = (
            USER_NOTES_PREAMBLE.format(path=USER_NOTES_file)
            + bounded_text(USER_NOTES_text, USER_NOTES_char_limit)
        )

workspace_instructions = ""
if workspace.exists:
    workspace_instructions = WORKSPACE_PREAMBLE.format(workspace_path=workspace.path)

    # A workspace README is the lightweight onboarding file for the current
    # project folder. If it exists, append it to the workspace section.
    workspace_overview_path = f"{workspace.path}/README.md"
    workspace_overview_path, workspace_overview_result = await read_convention_file(workspace_overview_path)
    if workspace_overview_result.metadata.get("status") == "completed":
        workspace_overview_text = workspace_overview_result.return_value
        if workspace_overview_text.strip():
            workspace_instructions += (
                WORKSPACE_README_PREAMBLE.format(readme_path=workspace_overview_path)
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
    # Support both flat skill files and folder-style skills with SKILL.md.
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
# Assemble the final instruction stack from broad to specific:
# stance -> vault policy -> workspace policy -> user notes -> workspace README -> skills.
instructions += "\n\n" + playbook_instructions
if workspace_playbook_instructions:
    instructions += "\n\n" + workspace_playbook_instructions
if USER_NOTES_instructions:
    instructions += "\n\n" + USER_NOTES_instructions
if workspace_instructions:
    instructions += "\n\n" + workspace_instructions
if skills_lines:
    instructions += (
        SKILLS_PREAMBLE
        + "\n".join(skills_lines)
    )

await assemble_context(history=history, instructions=instructions)
```
