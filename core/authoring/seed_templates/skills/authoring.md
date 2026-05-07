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
- For incremental file processing, first use `file_ops_safe(...)` to list, search, or otherwise select candidate files, then pass that result to `pending_files(operation="get", items=...)`. `pending_files` does not accept `path`, `pattern`, `glob`, or `search_term` directly. Inspect each returned item's `metadata["pending_diff"]` before writing custom diff or regex comparison logic. When available, `pending_diff["text"]` is the built-in unified diff since this workflow or chat scope last completed that file.
- When the script could use either deterministic parsing or `delegate(...)`, present both options to the user and ask for their preference. Parsing is cheaper and repeatable; delegation is often better for ambiguous extraction, summarization, classification, or judgment.
- Use `delegate(...)` only when the script needs model judgment, and pass explicit instructions and tool access.
- Make one small change at a time.

Offer to test using `run_workflow` tool. Note that this can only test workflow scripts, not context assemblys scripts. Fix any errors returned by the tool. Even if no errors are returned, inspect the artifacts to ensure they meet requirements.
