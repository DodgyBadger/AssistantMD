# Tips for building workflows

🔶 Use the Chat UI in `Workflow Creation` mode to help you build workflow files and refine the prompts.

🔶 Start with worflows disabled and test by running manually from the Workflow tab in the web interface. Enable and rescan when you are happy with the outputs.

🔶 Start simple, test and refine. One step with a compound prompt might do the trick. If not, split the prompt into two or more steps. Remember that each step can define a different `@model`, allowing for fine grained cost control.

🔶 Context is not passed automatically between steps. Use the `@output-file` of a previous step as `@input-file` in later steps to pass context. Nothing is assumed - you are always in control. You can have steps that build goals or checklists for later steps to process, allowing dynamic behaviour.

🔶 Consider Tavily extract and crawl as experimental tools. If any web tool returns greater than the `web_tool_max_tokens` setting (configurable in the web interface), the LLM will get a message that the tool call cannot be completed and will notify you. This is a blunt solution to ensure the app doesn't crash. Better context management strategies are being considered.

🔶 If using Obsidian, set up a base (Obsidian v1.9 or later) to view and manage all your workflow files and frontmatter properties in one place, making it easy to enable/disable or update schedules.

🔶 If using Obsidian, enabled `Use [[Wikilinks]]` and set `New link format` to `Absolute path in vault` in `Settings > Files & Links`. This will allow you to drag-and-drop from the Obsidian file explorer into input-file and output-file directives. AssistantMD will simply ignore the square brackets (`[[filename]]`).

🔶 In model configuration in the web interface, you create aliases for each provider model string. This allows updating to the latest models without needing to edit all your workflows.


