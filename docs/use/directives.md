# Directives

Directives are special commands that control how workflow steps execute. All directives:
- Must be placed at the very beginning of a step section
- Use the format `@directive-name value` or `@directive-name: value`
- Are processed before the step content is sent to the AI

## Directives

**@output-file** (string, optional)
- Specifies where the step's AI-generated content should be written
- Format: `@output-file path/to/file` or `@output-file [[path/to/file]]`
- Path resolution: All paths are relative to the vault root
- Automatic .md extension: The system automatically adds `.md` extension if not present
- **Best Practice**: Choose one approach per step:
  - **Explicit outputs**: Use @output-file for predictable, workflow-controlled file creation (recommended for most workflows)
  - **Tool-managed outputs**: Omit @output-file and enable file_ops_safe to let the LLM manage all file creation
  - **Avoid mixing both**: Using @output-file AND file_ops_safe in the same step creates unpredictable outputs (LLM response goes to @output-file, but LLM may also create additional files)

You may use time patterns in the output-file directive to generate files dynamically. See [Pattern Reference](patterns.md) for all available patterns.

---

**@input-file** (string, optional)
- File contents are included as additional context for the step
- Format: `@input-file path/to/file` or `@input-file [[path/to/file]]`
- Multiple files: Use multiple `@input-file` directives for multiple files
- Path resolution: All paths are relative to the vault root
- Automatic .md extension: The system automatically adds `.md` extension if not present
- When the optional parameter `(required)` or `(required=true)` is specified, the step will be skipped if no files are found for this @input-file directive. Useful for workflows that should only run when input data is available (e.g., only generate invoices when there are billable hours to process).
- When the optional parameter `(paths-only)` / `(paths_only)` is specified, the directive passes only file paths into the prompt (listed as bullet points) and does not inline file contents. Use this when you want the model or tools to open the files one-by-one instead of loading large contexts directly.

Examples:
- `goals.md` or `projects/notes.md` - Specific file
- `reports/*.md` - All files in the reports folder
- `timesheets/{pending} (required, paths_only)` - Only run if unprocessed timesheets exist and pass only the file paths

You may use time patterns and glob patterns in the input-file directive to retrieve files dynamically. See [Pattern Reference](patterns.md) for all available patterns.

**Security restrictions:** All paths are relative to the vault root and cannot access system files outside of that. Recursive patterns (`**`) and parent directory access (`..`) are not allowed.

---

**@header** (string, optional)
- Specifies a custom markdown header to prepend to the step's output
- Format: `@header Header Text`
- Supports pattern variables for dynamic headers (e.g., `{today}`, `{this-week}`)
- The header is written as a level 1 markdown heading (`# Header`) at the beginning of the step's output
- Only works when `@output-file` is specified (no output file means no header to write)

Examples:
- `@header Daily Planning` - Simple literal header
- `@header Planning for {today}` - Header with date (e.g., "Planning for 2025-01-15")
- `@header {day-name} Review` - Header with day name (e.g., "Monday Review")
- `@header Week of {this-week}` - Header with week start date

---

**@model** (string, optional)
- Specifies which AI model to use for this step
- Format: `@model model-name`
- Default behavior: If omitted, uses the DEFAULT_MODEL from settings in the UI.
- Available Models: See models section in the Configuration tab of the UI.
- Add `(thinking)` or `(thinking=true)` parameter to enable model reasoning/thinking
  - **Experimental**: Currently only affects Anthropic models
  - **Anthropic**: Enables thinking with 2000 token budget
  - **OpenAI**: Reasoning is on by default for GPT-5 family. Use non-reasoning models if you don't want reasoning
  - **Google**: Thinking is on by default for Gemini 2.5 models. Use earlier versions if you don't want thinking
  - **Mistral**: Use Magistral family for reasoning capabilities

---

**@write-mode** (string, optional)
- Controls how content is written to the output file
- Format: `@write-mode append`
- Available modes:
- `append`: Default. Append content to the end of the file
- `new`: Create new numbered files for each run (e.g., planning_001.md, planning_002.md)

---

**@run-on** (string, optional)
- Controls which days of the week a step should execute
- Format: `@run-on monday, friday` or `@run-on daily` or `@run-on never`
- Default behavior: If omitted, step runs every day the workflow is scheduled
- **Use case**: Allows different steps to run on different days within a single workflow, avoiding the need to create multiple workflow files with different schedules
- Supports comma or space separation between days
- Valid day names: Full names (`monday`, `tuesday`, `wednesday`, `thursday`, `friday`, `saturday`, `sunday`) or abbreviations (`mon`, `tue`, `wed`, `thu`, `fri`, `sat`, `sun`)
- Special keywords:
  - `daily` - Run every day the workflow is scheduled (same as omitting the directive)
  - `never` - Never run this step automatically (useful for disabling steps temporarily)
- Case insensitive: `Monday`, `MONDAY`, and `monday` are all valid

**How it works with schedule:**
The `schedule` in YAML frontmatter determines when the workflow runs. The `@run-on` directive determines which steps execute during that run. For example, an workflow scheduled daily at 8am can have steps that only run on specific days - weekly planning on Mondays, daily tasks on weekdays, and weekly reviews on Fridays - all in one workflow file.

---

**@tools** (string, optional)
- Enables tools for the step, allowing the AI to perform actions beyond text generation
- Tools are disabled by default and must be explicitly enabled per step
- Format: `@tools tool1, tool2` or `@tools tool1 tool2`
- Available tools can be viewed in the web UI Chat tab under Chat Settings. Copy the name shown into the directive (e.g. `file_ops_safe`)
- the Tavily tools require API keys to be set in the web UI Configuration tab. The `code_execution` tool defaults to the public Piston API (no key needed); edit `piston_base_url` in Configuration (or `PISTON_BASE_URL` env) and optionally `PISTON_API_KEY` if your endpoint requires it.
