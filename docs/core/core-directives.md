# Core Directives Reference

Directives are special commands that control how workflow steps execute. All directives:
- Must be placed at the very beginning of a step section
- Use the format `@directive-name value` or `@directive-name: value`
- Are processed before the step content is sent to the AI

## Directives

**@output-file** (string, optional)
- Specifies where the step's AI-generated content should be written
- Format: `@output-file path/to/file` or `@output-file [[path/to/file]]`
- Path resolution: All paths are relative to the vault root directory
- Automatic .md extension: The system automatically adds `.md` extension if not present
- Obsidian hotlinks: Square brackets (`[[filename]]`) are automatically stripped for drag-and-drop compatibility
- **Obsidian users**: Enable "Use [[Wikilinks]]" and set "New link format" to "Absolute path in vault" in Settings > Files & Links for drag-and-drop to work properly
- **Optional**: If omitted, step executes for side effects only (e.g., tool-based file operations, analysis without output)
- **Best Practice**: Choose one approach per step:
  - **Explicit outputs**: Use @output-file for predictable, workflow-controlled file creation (recommended for most workflows)
  - **Tool-managed outputs**: Omit @output-file and enable file_ops tools to let the LLM manage all file creation
  - **Avoid mixing both**: Using @output-file AND file_ops write operations in the same step creates unpredictable outputs (LLM response goes to @output-file, but LLM may also create additional files)

You may use time patterns in the output-file directive to generate files dynamically. See [Pattern Reference](patterns.md) for all available patterns.

**@input-file** (string, optional)
- Includes file content as context for the AI step
- Format: `@input-file path/to/file` or `@input-file [[path/to/file]]`
- Optional parameter: `@input-file path/to/file (required)` or `(required=true)`
- Multiple files: Use multiple `@input-file` directives for multiple files
- Path resolution: All paths are relative to the vault root directory
- Automatic .md extension: The system automatically adds `.md` extension if not present
- Obsidian hotlinks: Square brackets (`[[filename]]`) are automatically stripped for drag-and-drop compatibility
- **Obsidian users**: Enable "Use [[Wikilinks]]" and set "New link format" to "Absolute path in vault" in Settings > Files & Links for drag-and-drop to work properly
- When `(required)` or `(required=true)` is specified, the step will be skipped if no files are found for this @input-file directive. Useful for workflows that should only run when input data is available (e.g., only generate invoices when there are billable hours to process).

Examples:
- `goals.md` - Specific file
- `projects/notes.md` - File in subfolder
- `timesheets/{pending} (required)` - Only run if unprocessed timesheets exist
- `reports/*.md (required)` - Only run if any reports are present

You may use time patterns and glob patterns in the input-file directive to retrieve files dynamically. See [Pattern Reference](patterns.md) for all available patterns.

**Security restrictions:** Recursive patterns (`**`) and parent directory access (`..`) are not allowed. Absolute paths starting from the root directory are also not allowed (`/path/to/myfile`).

**@header** (string, optional)
- Specifies a custom markdown header to prepend to the step's output
- Format: `@header Header Text` or `@header Header with {today}`
- Supports pattern variables for dynamic headers (e.g., `{today}`, `{this-week}`, `{day-name}`)
- The header is written as a level 1 markdown heading (`# Header`) at the beginning of the step's output
- Only works when `@output-file` is specified (no output file means no header to write)
- Pattern support: Time-based patterns only - `{pending}` and multi-file patterns like `{latest:3}` are not supported

Examples:
- `@header Daily Planning` - Simple literal header
- `@header Planning for {today}` - Header with date (e.g., "Planning for 2025-01-15")
- `@header {day-name} Review` - Header with day name (e.g., "Monday Review")
- `@header Week of {this-week}` - Header with week start date

You may use time patterns in the header directive to generate dynamic headers. See [Pattern Reference](patterns.md) for all available patterns.

**@model** (string, optional)
- Specifies which AI model to use for this step
- Format: `@model model-name` or `@model model-name (thinking)`
- Default behavior: If omitted, uses the DEFAULT_MODEL from your environment configuration
- Available Models: See models section in the Configuration tab of the UI.
- Includes `test` model to avoid API costs
- Add `(thinking)` or `(thinking=true)` to enable model reasoning/thinking
  - **Experimental**: Currently only affects Anthropic models
  - **Anthropic**: Enables thinking with 2000 token budget
  - **OpenAI**: Reasoning is on by default for GPT-5 family. Use non-reasoning models if you don't want reasoning
  - **Google**: Thinking is on by default for Gemini 2.5 models. Use earlier versions if you don't want thinking
  - **Mistral**: Use Magistral family for reasoning capabilities
  - **Default**: Behavior varies by provider and model

**@write-mode** (string, optional)
- Controls how content is written to the output file
- Format: `@write-mode mode`
- Available modes: `append` (default), `new`
- `append`: Append content to existing file, creating cumulative documents
- `new`: Create new numbered files for each run (e.g., planning_001.md, planning_002.md)

**@run-on** (string, optional)
- Controls which days of the week a step should execute
- Format: `@run-on monday, friday` or `@run-on daily` or `@run-on never`
- Default behavior: If omitted, step runs every day the assistant is scheduled
- **Use case**: Allows different steps to run on different days within a single assistant, avoiding the need to create multiple assistant files with different schedules
- Supports comma or space separation between days
- Valid day names: Full names (`monday`, `tuesday`, `wednesday`, `thursday`, `friday`, `saturday`, `sunday`) or abbreviations (`mon`, `tue`, `wed`, `thu`, `fri`, `sat`, `sun`)
- Special keywords:
  - `daily` - Run every day the assistant is scheduled (same as omitting the directive)
  - `never` - Never run this step automatically (useful for disabling steps temporarily)
- Case insensitive: `Monday`, `MONDAY`, and `monday` are all valid

**How it works with schedule:**
The `schedule` in YAML frontmatter determines when the assistant runs. The `@run-on` directive determines which steps execute during that run. For example, an assistant scheduled daily at 8am can have steps that only run on specific days - weekly planning on Mondays, daily tasks on weekdays, and weekly reviews on Fridays - all in one assistant file.

Examples:
- `@run-on monday` - Only run on Mondays
- `@run-on monday, wednesday, friday` - Run on specific weekdays
- `@run-on mon, wed, fri` - Same as above using abbreviations
- `@run-on saturday, sunday` - Weekend only
- `@run-on daily` - Run every scheduled day (explicit version of default)
- `@run-on never` - Disable this step

**@tools** (string, optional)
- Enables AI tools for the step, allowing the AI to perform actions beyond text generation
- Tools are disabled by default and must be explicitly enabled per step
- Format: `@tools tool1, tool2` or `@tools tool1 tool2`
- Available tools: `web_search`, `code_execution`, `file_ops_safe`, `file_ops_unsafe`, `tavily_extract`, `tavily_crawl`
- Special keywords:
  - `all` (`true`, `yes`, `1`, `on`) - Enable all available tools
  - `none` (`false`, `no`, `0`, `off`) - Disable all tools
- **Security Note**: Exercise caution when combining `file_ops_unsafe` with web tools (extract, crawl, search) as there is a risk of prompt injection from untrusted web content. See [Security Considerations](../security.md) for details.
