# Assistant Setup Guide

An assistant is a markdown file in a vault's `assistants/` folder (or subfolder) that defines an automated AI workflow.

**Organization**: Assistants can be organized into subfolders (one level deep) for better organization. Folders prefixed with underscore (e.g., `_chat-sessions`) are ignored.

## Step Workflow

Step workflows execute predefined steps in sequence, typically on an automatic schedule. Use when you want automated, repeatable tasks that run consistently.

**Common uses:**
- Daily planning and task generation
- Weekly reviews and summaries
- Automated content processing
- Scheduled file organization

---

## Complete Template

See **[workflows/step-template](workflows/step-template.md)** for a complete, valid assistant file you can use as a starting point.

**Key structure:**
1. YAML frontmatter between `---` delimiters (required)
2. Optional `## INSTRUCTIONS` section for AI system instructions
3. One or more `## STEP1`, `## STEP2`, etc. sections with directives and prompts

---

## Learn More

Explore detailed documentation for each component:

- **[YAML Frontmatter](core/yaml-frontmatter.md)** - Schedules, workflows, and settings
- **[Core Directives](core/core-directives.md)** - File input/output, models, and tools (@input-file, @output-file, @model, @tools, etc.)
- **[Pattern Variables](core/patterns.md)** - Dynamic file names using {today}, {this-week}, etc.
- **[Step Workflow Details](workflows/step.md)** - Advanced features and examples
