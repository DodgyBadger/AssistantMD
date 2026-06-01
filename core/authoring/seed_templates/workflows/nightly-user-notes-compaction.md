---
run_type: workflow
schedule: "cron: 30 2 * * *"
enabled: false
description: Compact vault-native user.md when it approaches the configured user notes character limit.
---

## Nightly user notes compaction

This workflow is disabled by default. Enable it after reviewing the `Save User Note`
skill policy and confirming you want nightly automatic curation of
`AssistantMD/user.md`.

```python
"""Compact vault-native user notes when they approach the configured limit."""

DEFAULT_CONTEXT_NOTES_FILE = "AssistantMD/user.md"
DEFAULT_CONTEXT_NOTES_CHAR_LIMIT = 6000
TRIGGER_RATIO = 0.8
CURATION_MODEL = "gpt-mini"
SKILL_PATH = "AssistantMD/Skills/save_user_note.md"
ARCHIVE_DIR = "AssistantMD/user_notes_archive"


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


def strip_markdown_fence(value):
    text = value.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if len(lines) >= 2 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text


def archive_path_for_today(index):
    suffix = "" if index == 0 else f"-{index}"
    return f"{ARCHIVE_DIR}/user-notes-{date.today('%Y-%m-%d')}{suffix}.md"


def compaction_prompt(context_notes_text, skill_policy, context_notes_file, target_chars, previous_text=""):
    retry_instruction = ""
    if previous_text:
        retry_instruction = (
            f"\n\nYour previous compacted version was {len(previous_text)} characters, "
            f"which is above the {target_chars} character target. Rewrite it more "
            "aggressively while preserving durable facts and preferences."
        )
    return (
        "Compact the following AssistantMD user notes file.\n\n"
        "Use the Save User Note skill policy as the user-notes contract. Preserve all durable "
        "facts and preferences. Remove duplicates, stale wording, and unnecessary prose. "
        f"Return only the complete replacement markdown for {context_notes_file}. "
        f"The replacement must be no more than {target_chars} characters so there is "
        "room for future updates before the context limit is reached."
        + retry_instruction
        + "\n\n=== SAVE USER NOTE SKILL POLICY ===\n"
        + skill_policy
        + "\n\n=== CURRENT USER NOTES FILE ===\n"
        + context_notes_text
    )


skill_frontmatter = await file_ops_safe(
    operation="frontmatter",
    path=SKILL_PATH,
    keys="context_notes_file,context_notes_char_limit",
)
context_notes_file = frontmatter_value(skill_frontmatter, "context_notes_file", DEFAULT_CONTEXT_NOTES_FILE)
context_notes_char_limit = parse_positive_int(
    frontmatter_value(skill_frontmatter, "context_notes_char_limit", DEFAULT_CONTEXT_NOTES_CHAR_LIMIT),
    DEFAULT_CONTEXT_NOTES_CHAR_LIMIT,
)
trigger_chars = int(context_notes_char_limit * TRIGGER_RATIO)

context_notes_result = await file_ops_safe(operation="read", path=context_notes_file)
if context_notes_result.metadata.get("status") != "completed":
    await finish(status="skipped", reason=f"{context_notes_file} not found")

context_notes_text = context_notes_result.return_value.strip()
if len(context_notes_text) <= trigger_chars:
    await finish(
        status="skipped",
        reason=f"{context_notes_file} is {len(context_notes_text)} chars; trigger is {trigger_chars}",
    )

skill_result = await file_ops_safe(operation="read", path=SKILL_PATH)
skill_policy = (
    skill_result.return_value
    if skill_result.metadata.get("status") == "completed"
    else "Preserve durable facts and preferences. Remove duplicates and stale detail."
)

compaction = await delegate(
    model=CURATION_MODEL,
    options={"thinking": "low"},
    prompt=compaction_prompt(context_notes_text, skill_policy, context_notes_file, trigger_chars),
)
curated_text = strip_markdown_fence(compaction.return_value)

retried = False
if curated_text and len(curated_text) > trigger_chars:
    retried = True
    retry = await delegate(
        model=CURATION_MODEL,
        options={"thinking": "low"},
        prompt=compaction_prompt(
            context_notes_text,
            skill_policy,
            context_notes_file,
            trigger_chars,
            previous_text=curated_text,
        ),
    )
    curated_text = strip_markdown_fence(retry.return_value)

if not curated_text:
    outcome = {
        "status": "completed_without_write",
        "reason": "delegate returned empty user notes content",
        "context_notes_file": context_notes_file,
        "original_chars": len(context_notes_text),
        "trigger_chars": trigger_chars,
        "retried": retried,
    }
elif len(curated_text) > trigger_chars:
    outcome = {
        "status": "completed_without_write",
        "reason": "delegate output exceeded compaction trigger after retry",
        "context_notes_file": context_notes_file,
        "original_chars": len(context_notes_text),
        "curated_chars": len(curated_text),
        "trigger_chars": trigger_chars,
        "retried": retried,
    }
else:
    await file_ops_safe(operation="mkdir", path=ARCHIVE_DIR)

    archive_path = ""
    for index in range(10):
        candidate = archive_path_for_today(index)
        existing = await file_ops_safe(operation="read", path=candidate)
        if existing.metadata.get("status") != "completed":
            archive_path = candidate
            break

    if not archive_path:
        outcome = {
            "status": "completed_without_write",
            "reason": "could not find available archive path",
            "context_notes_file": context_notes_file,
            "original_chars": len(context_notes_text),
            "curated_chars": len(curated_text),
            "trigger_chars": trigger_chars,
            "retried": retried,
        }
    else:
        moved = await file_ops_safe(
            operation="move",
            path=context_notes_file,
            destination=archive_path,
        )
        if moved.metadata.get("status") != "completed":
            outcome = {
                "status": "completed_without_write",
                "reason": "failed to archive original user notes file",
                "context_notes_file": context_notes_file,
                "archive_path": archive_path,
                "move_result": moved.return_value,
                "retried": retried,
            }
        else:
            written = await file_ops_safe(
                operation="write",
                path=context_notes_file,
                content=curated_text.rstrip() + "\n",
            )
            outcome = {
                "status": "completed" if written.metadata.get("status") == "completed" else "completed_with_errors",
                "context_notes_file": context_notes_file,
                "archive_path": archive_path,
                "original_chars": len(context_notes_text),
                "curated_chars": len(curated_text),
                "context_notes_char_limit": context_notes_char_limit,
                "trigger_chars": trigger_chars,
                "write_result": written.return_value,
                "retried": retried,
            }

outcome
```
