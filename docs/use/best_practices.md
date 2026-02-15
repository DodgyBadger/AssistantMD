# Best Practices

Guidance for using AssistantMD effectively.

## General

- Use the assistantmd_helper template to get information about this app. It has access to docs folder and can answer questions about AssistantMD or even directly build workflow and context templates with file_ops_safe.
- If using Obsidian, set up a base (Obsidian v1.9 or later) to view and manage all your workflow files and frontmatter properties in one place, making it easy to enable/disable or update schedules.
- If using Obsidian, enabled `Use [[Wikilinks]]` and set `New link format` to `Absolute path in vault` in `Settings > Files & Links`. This will allow you to drag-and-drop from the Obsidian file explorer into input and output directives. AssistantMD will simply ignore the square brackets (`[[filename]]`).


## Workflow and Context Templates

- Start with workflows disabled and test by running manually from the Workflow tab.
- Begin with a single step, test and then build up as needed to get reliable output.
- Context is not passed automatically between steps. Use `@output variable:foo` + `@input variable:foo` to pass context (or file:name if you want greater observability).
- Each step can define a different `@model`, allowing for fine grained cost control. Prefer smaller models for lightweight steps and reserve larger models for critical reasoning.
- For large tool outputs, prefer `@input variable:NAME` in later steps instead of additional tool calls.
- Using both the `@output` directive AND `file_ops_safe` tool in the same step can cause duplicate file create. Make sure your prompt clearly distinguishes tool use vs LLM response.

