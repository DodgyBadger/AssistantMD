---
name: Workflow Authoring
description: Guidelines for creating and modifying AssistantMD workflows and context templates.
---

Read `__virtual_docs__/use/authoring.md` for file shape and frontmatter field reference before starting.

Inspect `__virtual_docs__/tools/code_execution_local.md` for current capability signatures and return shapes. Do not guess — check the contract.

When creating or editing authoring files:
- `AssistantMD/Authoring/` is the canonical location for all workflows and context templates.
- Every file needs `run_type: workflow` or `run_type: context` in frontmatter plus exactly one fenced `python` block.
- Use the compile tool to check for syntax errors before asking the user to run.
- Make one small change at a time. Test before continuing.
- Do not treat existing vault workflow files as authoritative examples of the current API.
