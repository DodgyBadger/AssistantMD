---
name: Authoring
description: Guidelines for creating and modifying AssistantMD workflows, context templates, and skills. Use when the user asks to create, edit, or debug any file in AssistantMD/Authoring/ or AssistantMD/Skills/.
---

## Workflows and context templates

Read `__virtual_docs__/use/authoring.md` for file shape and frontmatter field reference before starting.

Inspect `__virtual_docs__/tools/code_execution.md` for current capability signatures and return shapes. Do not guess — check the contract.

- `AssistantMD/Authoring/` is the canonical location for all workflows and context templates.
- Every file needs `run_type: workflow` or `run_type: context` in frontmatter plus exactly one fenced `python` block.
- Use the compile tool to check for syntax errors before asking the user to run.
- Make one small change at a time. Test before continuing.
- Do not treat existing vault workflow files as authoritative examples of the current API.

## Skills

Skills are plain markdown files in `AssistantMD/Skills/`. The agent reads all skill descriptions at session start and loads the body only when the skill triggers.

### File format

```markdown
---
name: skill-name
description: What this skill does and when to use it.
---

Body: instructions, procedures, examples.
```

Only `name` and `description` are required in frontmatter. Do not add other fields.

### Description is the trigger

The description is the primary mechanism for deciding when a skill activates — it is always in context, the body is not. Put all "when to use" information in the description. A "When to Use" section in the body is useless because the body only loads after triggering.

Good description: *"Step-by-step guide for rotating, splitting, and extracting pages from PDFs. Use when the user needs to manipulate PDF files."*

### Concise is key

The context window is shared with conversation history, other skill descriptions, and the user's request. Only include what Claude doesn't already know. Challenge every sentence: does this justify its token cost? Prefer a short example over a long explanation.

### Set appropriate degrees of freedom

- **High freedom** (plain prose): when multiple approaches are valid or context drives the decision
- **Medium freedom** (pseudocode, patterns): when a preferred approach exists but variation is acceptable
- **Low freedom** (exact steps or code): when the operation is fragile or a specific sequence must be followed

### Progressive disclosure

Keep the body lean. For complex skills, reference other vault files rather than loading everything upfront — tell Claude when to read them:

```markdown
For the full schema, read `References/db-schema.md`.
For brand assets, use files in `Assets/brand/`.
```

### What not to include

Do not create README files, changelogs, or auxiliary docs alongside skill files. The skill body should contain only what an agent needs to do the job.
