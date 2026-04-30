---
name: Authoring
description: Guidelines for creating and modifying AssistantMD workflow scripts, context assembly scripts, and skills. Use when the user asks to create, edit, or debug any file in AssistantMD/Authoring/ or AssistantMD/Skills/.
---

Use this skill when creating or editing AssistantMD authoring files:

- workflow scripts
- context assembly scripts
- skill files

Before changing files, read the current contract docs:

- `__virtual_docs__/use/build-guide.md` for skill behavior and the built-in skill discovery script.
- `__virtual_docs__/use/authoring.md` for workflow and context script structure.
- `__virtual_docs__/tools/code_execution.md` for Monty runtime features, helper signatures, direct tool calls, and return shapes.

Do not infer the current API from older vault files. Existing user files may predate the current authoring contract.

When writing authoring scripts:

- Keep user-editable constants such as paths, prompts, model aliases, and thinking settings near the top.
- Use direct tool calls and helper functions exactly as documented.
- Use `delegate(...)` only when the script needs model judgment, and pass explicit instructions and tool access.
- Make one small change at a time.

Offer to test using `run_workflow` tool. Note that this can only test workflow scripts, not context assemblys scripts. Fix any errors returned by the tool. Even if no errors are returned, inspect the artifacts to ensure they meet requirements.
