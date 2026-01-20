# Subagent Tool Implementation Plan

**Purpose**: Enable primary agents (chat, workflows, context manager) to delegate a focused, stateless task to a separate LLM instance and receive a concise report, while preserving the user-selected tool permissions and model controls.
**Note**: This plan assumes a future global cancel-agent API will be available; subagent runs should plug into the same cancellation framework once implemented.
**Potential safeguards**: Optional settings to limit subagent cost/impact, such as max runtime/timeout per subagent call, max tokens per subagent run, max subagent calls per parent run, and a default tool allowlist/denylist for subagents.

## Step 1: Design + settings scaffolding
- Confirm naming and constraints (stateless prompt-only, no caller model override, tool access inherited).
- Add new general setting key (e.g., `subagent_default_model`) to settings template and system settings for UI/config visibility.
- Add new tool entry `subagent` to tools config (template + system) so it can be enabled via `@tools` and UI.

Stop point: run config/schema-related tests or startup checks if available.

## Step 2: Core implementation
- Add `core/tools/subagent.py` implementing `BaseTool`.
- Tool signature: `subagent(prompt: str) -> str` (async).
- Resolve model: use `subagent_default_model` if set; otherwise use caller model from `RunContext`.
- Tool access: inherit caller toolset, excluding `subagent` itself to prevent recursion.
- Add fixed system instruction constant in `core/constants.py` (e.g., `SUBAGENT_SYSTEM_INSTRUCTION`).

Stop point: run unit tests or targeted tool tests.

## Step 3: Integration wiring
- Ensure tool is discoverable by `ToolsDirective` via settings, and usable in:
  - Chat UI (selected tools list)
  - Workflow steps (`@tools subagent`)
  - Context manager steps (`@tools subagent`)
- Verify `RunContext` access for tool inheritance in each surface.

Stop point: run chat/workflow smoke tests (if present).

## Step 4: Documentation
- Update docs to describe the `subagent` tool, scope, and model-selection order.
- Add guidance on stateless behavior and permission inheritance.

Stop point: optional doc-only checks.

## Step 5: Validation framework
- Add/extend a validation scenario that:
  - Enables `subagent` tool.
  - Executes a workflow or chat prompt that delegates to subagent.
  - Asserts a stable, expected response format and no tool escalation.

Final stop point: run validation scenario(s).
