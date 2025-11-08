# Workflow patterns

AssistantMD supports a spectrum of automation patterns - from fully prescribed workflows to flexible agents.

## The Two Ends of the Spectrum

### Explicit Workflows

Characterized by:
- Multiple explicitly defined steps (STEP1, STEP2, STEP3...)
- Heavy use of directives: `@input-file`, `@output-file`, `@write-mode`
- Predictable file locations and naming
- Clear execution flow where each step builds on previous outputs

**What it enables**: Scheduled automation, repeatable processes, workflows where consistency and predictability are essential.

Examples:
- Daily planning workflows
- Weekly review automation
- Scheduled content generation
- Multi-step report compilation

### Flexible Agents

Characterized by:
- Single step workflows (or very few steps)
- Use of `@tools file_ops_safe, file_ops_unsafe` instead of `@input-file`/`@output-file`
- No prescribed output locations - agent manages all file operations
- High-level goal with minimal execution guidance

**What it enables**: Flexible problem-solving, exploration, dynamic task breakdown, self-organized outputs.

Examples:
- Research and analysis projects
- Data exploration with self-managed outputs
- Complex tasks where the approach should be determined dynamically
- Prototyping workflows before defining explicit structure

## The Spectrum in Practice

Between these extremes, you can mix approaches - use some explicit steps with controlled outputs, while allowing other steps to operate more autonomously with file tools. The pattern you choose depends on how much control you need versus how much flexibility you want the assistant to have.

## Tips & Best Practices

### For Flexible Agents

- **Be explicit about file-based task tracking**: In your instructions, tell the agent to create a task list file and update it as work progresses. Without this guidance, the agent may track tasks only in its context window.
- **Start with clear meta-instructions**: Define the workflow pattern you want ("break down into steps, track progress, execute systematically") before giving the specific goal.
- **Simplify goals for faster iteration**: Complex goals with web search or extensive analysis can take time. Start with simpler, focused goals to validate the autonomous pattern.
- **Review Logfire traces**: The cloud dashboard shows exactly how the agent approached the task - what files it created, in what order, and why.
