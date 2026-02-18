# Reference

[Directives](#directives) | [Frontmatter](#frontmatter) | [Patterns](#patterns) | [Buffers](#buffers) | [Routing](#routing)

## Directives

Syntax: `@directive value (optional params)` or `@directive: value (optional params)`  
Directives must be at the start of a step/section, before normal prompt text.  
File paths are vault-relative. For `file:` targets, `.md` is auto-added if missing.

<details>
<summary>@output</summary>

Applies to: Workflow, Context Template  
Description: Route step output to one or more destinations.

### Values:
`file: PATH`  
Output to a file.

`variable: NAME`  
Output to a buffer variable.

`context`  
Output to the chat agent context. Only applicable in context templates.

### Optional params:
`scope=session|run`  
Only applies to variable outputs. `run` scoped to the current run (default for workflows/context templates). `session` persists across chat turns for the same session and can be read by both context manager and chat agent.

### Notes:
- Multiple `@output` directives are allowed.

### Examples:
- `@output file: reports/{today}`
- `@output variable: foo`
- `@output variable: summary (scope=session)`
- `@output context`

</details>

<details>
<summary>@input</summary>

Applies to: Workflow, Context Template  
Description: Read in file/buffer content (or references) as step context.

### Values:
`file: PATH`  
Read in file content.

`variable: NAME`  
Read content from an in-memory buffer variable.

### Optional params:

`required` or `required=true`  
Skip the step when no matching input is found.

`refs_only`  
Pass references only instead of full content - file path or variable name.

`head=N`  
Inline only the first `N` characters per resolved input (file or variable).

`properties` or `properties="KEY1,KEY2"`  
Inline frontmatter properties only. With no value, includes all properties. With keys, includes only matching properties.

`output=DEST`  
Route resolved input to `inline` (default if omitted), `file:`, `variable:` or `context` (context templates only).

`write_mode=append|replace|new`  
Applies when `output=` routes to `file:` or `variable:` destinations.

`scope=session|run`  
If used with `output=`, behaviour matches `@output` directive for variable destinations. Otherwise it controls where input variable is read from (run or session scope).  
E.g. `@input variable:foo (scope=session)` reads foo from  session scope. This can be used to pass data between chat agent and context manager.

### Notes:
- Use multiple `@input` directives if you want to load multiple sources. Comma separated list on a single directive does not work.
- In context templates, `@input file:myfile (output=context)` will route the file contents immediately into chat agent context, bypassing the LLM.  
- Precedence is `refs_only` > `properties` > `head`.
- If `properties` is enabled and no frontmatter properties are found, input falls back to refs-only for that item.
- If a parameter value contains commas (for example `properties` key lists), wrap the value in quotes.

### Examples:
- `@input file: notes/*.md`
- `@input variable: foo`
- `@input file: inbox/{pending:5} (required, refs_only)`
- `@input file: notes/large.md (head=2000)`
- `@input file: Projects/Plan (properties="status,owner")`
- `@input file: inbox/{pending:3} (output=variable: batch, write_mode=new)`

</details>

<details>
<summary>@header</summary>

Applies to: Workflow  
Description: Prepend a level-1 heading to output file content.

### Values:
`TEXT`  
Free text heading. Pattern variables are supported.

### Optional params:
No optional parameters.

### Notes:
Applied only when `@output` is present.

### Examples:
- `@header Weekly Review`
- `@header Planning for {today}`

</details>

<details>
<summary>@model</summary>

Applies to: Workflow, Context Template  
Description: The model to use for this step. If omitted, default model in settings is used.

### Values:
`MODEL_ALIAS`  
Use a configured model alias from settings.

`none`  
Skip the LLM call for this step.

### Optional params:
`thinking` or `thinking=true`  
Enable provider/model-specific reasoning behavior.

### Notes:
Thinking operates differently across models:
- Anthropic: `thinking` currently enables a 2000-token thinking budget.
- OpenAI: GPT-5 family reasons by default; use non-reasoning models to avoid this behavior.
- Google: Gemini 2.5 models reason by default; use earlier versions to avoid this behavior.
- Mistral: use Magistral family for reasoning capabilities.

### Examples:
- `@model gpt-mini`
- `@model none`
- `@model sonnet (thinking=true)`

</details>

<details>
<summary>@write_mode</summary>

Applies to: Workflow  
Description: Control how `@output` files are written.

### Values:
`append`  
Default mode. Append new output to the file.

`replace`  
Overwrite the file with new output.

`new`  
Create numbered files for each run.

### Optional params:
No optional parameters.

### Examples:
- `@write_mode append`
- `@write_mode replace`
- `@write_mode new`

</details>

<details>
<summary>@run_on</summary>

Applies to: Workflow  
Description: Limit which days a step executes.

### Values:
`monday` ... `sunday` or `mon` ... `sun`  
Full day names or abbreviations.

`daily` (default if omitted)
Run every scheduled day.

`never`  
Disable automatic runs for the step.

### Optional params:

No optional parameters.

### Notes:
Supports multiple values separeated by comma or space.  
Case-insensitive.  
Allows more complex workflows. E.g. workflow runs daily, but step 1 runs only Monday, step 2 runs only Friday.

### Examples:
- `@run_on monday, friday`
- `@run_on mon fri`
- `@run_on daily`
- `@run_on never`

</details>

<details>
<summary>@tools</summary>

Applies to: Workflow, Context Template  
Description: Enable one or more tools for the step.

### Values:
`TOOL_ID`  
Tool IDs from Chat Settings UI.

### Optional params:
`output=DEST`  
Per-tool output routing destination.

`write_mode=append|replace|new`  
Per-tool file write behavior when routing to file.

`scope=session|run`  
Only for `variable:` destinations.

### Notes:
Supports multiple values separeated by comma or space.  
Tool names must match IDs from Chat Settings.  
Tavily tools require API keys in Configuration.  
`code_execution` defaults to public Piston; configure `piston_base_url` and optional `PISTON_API_KEY` to self-host.  
`scope` only matters when output is routed to `variable:`.  

### Examples:
- `@tools file_ops_safe`
- `@tools web_search, file_ops_safe`
- `@tools file_ops_safe(output=variable: tool_buffer)`
- `@tools file_ops_safe(output=file: tool-outputs/listing, write_mode=replace)`

</details>

<details>
<summary>@cache</summary>

Applies to: Context Template  
Description: Cache step output for reuse, saving LLM call on future runs.

### Values:
`session`  
Cache for the current chat session.

`daily`  
Cache for the current day.

`weekly`  
Cache for the current week.

`30s`, `10m`, `2h`, `1d`  
Cache for duration.

### Optional params:
No optional parameters.

### Notes:
Cache expires if the context template is edited.  
Gating directives can bypass cache.  
No cache if omitted.

### Examples:
- `@cache 24h`
- `@cache session`
- `@cache weekly`

</details>

<details>
<summary>@recent_runs</summary>

Applies to: Context Template  
Description: Number of recent chat runs provided to the context manager step. Saves tokens if you only need to reason over the most recent messages.

### Values:
`INTEGER`  
Include the most recent N runs.

`all`  
Include full run history.

`0` (default if omitted)  
Include no recent runs.

### Optional params:
No optional parameters.

### Examples:
- `@recent_runs 3`
- `@recent_runs all`
- `@recent_runs 0`

</details>

<details>
<summary>@recent_summaries</summary>

Applies to: Context Template  
Description: Number of recent context manager summaries (the combined output of all steps) provided to the step. Can be used to save tokens by feeding recent_summaries instead of full transcript, or to detect context drift.

### Values:
`INTEGER`  
Include the most recent N summaries.

`all`  
Include all available summaries.

`0` (default if omitted)
Include no summaries.

### Optional params:
No optional parameters.

### Examples:
- `@recent_summaries 3`
- `@recent_summaries all`

</details>

## Frontmatter

Syntax: `key: value`  
Frontmatter is YAML between `---` delimiters.  
Canonical style uses snake_case keys.  
Quotes are optional but recommended to avoid display issues in Obsidian. E.g. `schedule: "cron: 0 8 * * *"`

<details>
<summary>workflow_engine</summary>

Applies to: Workflow  
Description: Select the workflow engine.

### Values:
`step`  
Currently only `step` is available.

### Optional params:
No optional parameters.

### Notes:
Required for workflows.

### Examples:
- `workflow_engine: step`

</details>

<details>
<summary>schedule</summary>

Applies to: Workflow  
Description: Define when the workflow runs.

### Values:
`cron: ...`  
Recurring schedule using 5-field cron syntax.

`once: ...`  
One-time schedule at an explicit datetime.

### Optional params:
No optional parameters.

### Notes:
- Omit for manual-only workflows.  
- Supported datetime formats include `once: 2025-12-25 10:00`, `once: 2025-12-25T10:00:00`, `once: December 25, 2025 at 10am`, and `once: 2025-12-25` (defaults to 9am).
- `once:` values must be explicit and in the future. Relative terms such as `tomorrow` or `next week` are not supported.

### Examples:
- `schedule: "cron: 0 9 * * *"`
- `schedule: "once: 2026-01-15 14:30"`

</details>

<details>
<summary>enabled</summary>

Applies to: Workflow  
Description: Enable / disable workflow.

### Values:
`true`  
Scheduled runs are active.

`false`  
Scheduled runs are paused.

### Optional params:
No optional parameters.

### Notes:
- Affects scheduled runs only; manual runs still work.
- Changing value requires vault rescan to take effect.

### Examples:
- `enabled: false`
- `enabled: true`

</details>

<details>
<summary>week_start_day</summary>

Applies to: Workflow, Context Template  
Description: Choose what day a week starts on for calculating pattern substituions.

### Values:
`monday`, `tuesday`, `wednesday`, `thursday`, `friday`, `saturday`, `sunday`  
Sets the start day used by weekly patterns.

### Optional params:
No optional parameters.

### Notes:
- Default is `monday`.

### Examples:
- `week_start_day: monday`
- `week_start_day: sunday`

</details>

<details>
<summary>passthrough_runs</summary>

Applies to: Context Template  
Description: Number of recent runs passed verbatim to the chat agent.

### Values:
`INTEGER`  
Pass the most recent N runs.

`all`  
Pass full run history.

`0`  
Pass no runs. Chat agent will receive only the context template output.

### Optional params:
No optional parameters.

### Examples:
- `passthrough_runs: 3`
- `passthrough_runs: all`
- `passthrough_runs: 0`

</details>

<details>
<summary>token_threshold</summary>

Applies to: Context Template  
Description: Run context manager only when chat history exceeeds this value.

### Values:
`INTEGER`  
Approximate token threshold used for gating.

### Optional params:
No optional parameters.

### Notes:
Below threshold, passthrough history is used directly.

### Examples:
- `token_threshold: 4000`
- `token_threshold: 25000`

</details>

<details>
<summary>description</summary>

Applies to: Workflow, Context Template  
Description: Human-readable metadata.

### Values:
`TEXT`  
Descriptive label.

### Optional params:
No optional parameters.

### Notes:
- Documentation only; no runtime behavior.
- Description is provided to the chat agent in `workflow_run` tool

### Examples:
- `description: Daily planning`
- `description: Weekly research synthesis`

</details>

<details>
<summary>Custom fields</summary>

Applies to: Workflow, Context Template  
Description: Extra metadata for your own organization.

### Values:
`ANY_YAML_KEY: ANY_YAML_VALUE`  
Custom metadata of your choice.

### Optional params:
No optional parameters.

### Notes:
Ignored by runtime.

### Examples:
- `team: ops`
- `project: q4-report`

</details>

## Patterns

Syntax: `{pattern}` or `{pattern:FORMAT}`  
Patterns substitute text in supported directive values.

<details>
<summary>{today}</summary>

Applies to: `@input`, `@output`, `@header`  
Description: Current date.
Supports `:FORMAT`. Default `YYYY-MM-DD`

### Examples:
- `@output file: daily/{today}`
- `@header Plan for {today:dddd}`

</details>

<details>
<summary>{yesterday}</summary>

Applies to: `@input`, `@output`, `@header`  
Description: Previous day date.
Supports `:FORMAT`. Default `YYYY-MM-DD`

### Examples:
- `@output file: daily/{yesterday}`
- `@input file: Journal/{yesterday:YYYYMMDD}`

</details>

<details>
<summary>{tomorrow}</summary>

Applies to: `@input`, `@output`, `@header`  
Description: Next day date.
Supports `:FORMAT`. Default `YYYY-MM-DD`

### Examples:
- `@output file: daily/{tomorrow}`
- `@header Prep for {tomorrow}`

</details>

<details>
<summary>{this-week}</summary>

Applies to: `@input`, `@output`, `@header`  
Description: Current week start date based on `week_start_day`.  
Supports `:FORMAT`. Default `YYYY-MM-DD`

### Examples:
- `@output file: reports/{this-week}`
- `@input file: Planner/{this-week}`

</details>

<details>
<summary>{last-week}</summary>

Applies to: `@input`, `@output`, `@header`  
Description: Previous week start date based on `week_start_day`.  
Supports `:FORMAT`. Default `YYYY-MM-DD`

### Examples:
- `@output file: reports/{last-week}`
- `@input file: Planner/{last-week}`

</details>

<details>
<summary>{next-week}</summary>

Applies to: `@input`, `@output`, `@header`  
Description: Next week start date based on `week_start_day`.  
Supports `:FORMAT`. Default `YYYY-MM-DD`

### Examples:
- `@output file: reports/{next-week}`
- `@output file: Planner/{next-week}`

</details>

<details>
<summary>{this-month}</summary>

Applies to: `@input`, `@output`, `@header`  
Description: Current month.
Supports `:FORMAT`. Default `YYYY-MM`

### Examples:
- `@output file: archive/{this-month}`
- `@header {month-name} Priorities`

</details>

<details>
<summary>{last-month}</summary>

Applies to: `@input`, `@output`, `@header`  
Description: Previous month.
Supports `:FORMAT`. Default `YYYY-MM`

### Examples:
- `@output file: archive/{last-month}`
- `@input file: Reviews/{last-month}`

</details>

<details>
<summary>{day-name}</summary>

Applies to: `@input`, `@output`, `@header`  
Description: Current day name (e.g. `Tuesday`).  
Supports `:FORMAT`. Default `dddd`

### Examples:
- `@header {day-name} Review`
- `@output file: logs/{day-name:ddd}`

</details>

<details>
<summary>{month-name}</summary>

Applies to: `@input`, `@output`, `@header`  
Description: Current month name (e.g. `February`).  
Supports `:FORMAT`. Default `MMMM`

### Examples:
- `@header {month-name} Plan`
- `@output file: plans/{month-name:MMM}`

</details>

<details>
<summary>{latest}</summary>

Applies to: `@input`  
Description: Most recent file/folder by date in name. `{latest:N}` returns N recent files.  
Does not support `:FORMAT`  
Notes: `{latest:N}` is not supported in folder position (for example `myfiles/{latest:3}/*.md`).

### Examples:
- `@input file: journal/{latest}`
- `@input file: journal/{latest:3}`

</details>

<details>
<summary>{pending}</summary>

Applies to: `@input`  
Description: Resolves to unprocessed files. `{pending:N}` returns N unprocessed files (default 10 if omitted).  
Does not support `:FORMAT`  
Notes: Tracking is per workflow and per pattern string. Files are marked processed after a step that uses `{pending}`. Later edits can re-queue files. Within the same run, files already marked processed are not revisited by later `{pending}` resolutions.

### Examples:
- `@input file: tasks/{pending:5}`
- `@input file: inbox/{pending} (required, refs_only)`

</details>

<details>
<summary>Glob patterns</summary>

Applies to: `@input`  
Description: Match files by wildcard expression.
Does not support `:FORMAT`  
Notes: Recursive `**` and parent `..` are not allowed.

### Examples:
- `@input file: notes/*.md`
- `@input file: projects/*draft*.md`

</details>

<details>
<summary>Format Tokens</summary>

Applies to: `@input`, `@output`, `@header`  
Description: Optional format suffix for time/name patterns.  
Resolves to: A formatted output using the provided `FORMAT` string on time/name patterns.  
Tokens can be combined with punctuation and literal text (for example `YYYY-MM-DD`, `MMMM DD`, `Week-of-YYYY`).

Tokens:
- `YYYY` e.g. 2026
- `YY` e.g. 26
- `MM` e.g. 01
- `M` e.g. 1
- `DD` e.g. 02
- `D` e.g. 2
- `MMMM` e.g. February
- `MMM` e.g. Feb
- `dddd` e.g. Monday
- `ddd` e.g. Mon
- `HH` e.g. 23
- `mm` e.g. 39
- `ss` e.g. 12


### Examples:
- `@output file: daily/{today:YYYYMMDD}`
- `{today:YYYYMMDD}`
- `{this-week:YYYY-MM-DD}`
- `{day-name:ddd}`

</details>

## Buffer

The buffer is an in-memory key-value store. Entries are called variables and use the `variable:name` scheme. Buffers can be used anywhere `file:` inputs/outputs are supported.

### Use cases
- Passing information between steps in a context template or workflow
- Protecting context window from huge data dumps and enabling systematic exploration
- LLM 'scratch pad'

### How scopes work:
- `run` scope is the default for workflows and context templates. A run-scoped variable exists only for the current run.
- `session` scope is the default for chat tools. A session-scoped variable persists across runs in the same chat session.
- The same variable name can exist in both scopes. `scope=session|run` selects which scope to read from or write to.
- `scope=` is supported anywhere a `variable:` target supports scope selection, including `@output`, `@input`, and routed tool outputs like `output=variable:foo`.

### Examples:
`@output variable: summary`  
Output is written to a variable named `summary`. Since `scope` is not specified, default is `run`, meaning this variable can only be read by steps in the same run.

`@output variable: summary (scope=session)`  
Same as above but scoped to the chat session, so the variable can be read by the chat agent and future runs of the context template within the same session.

`@input variable: summary`  
Read contents of the variable `summary`. Since `scope` is not specified, default is `run`.


## Routing

Routing redirects directive or tool outputs to an alternate destination instead of inlining content.

### Destinations:
- `inline` keeps content in the normal prompt/response flow. This is default route and not needed unless you want it explicit.
- `variable: NAME` writes content to a buffer variable.
- `file: PATH` writes content to a file.
- `context` injects content directly into chat-agent context (context templates only).

### How it works:
- Use `output=DEST` to route `@input` or tool output to a destination.
- Use `write_mode=append|replace|new` when routed output is written to `file:` or `variable:` destinations.
- Use `scope=session|run` with `variable:` destinations to select buffer scope.
- Some tools may not accept routing parameters.

### Examples:
`@input variable: notes (output=file: exports/notes)`  
The contents of variable `notes` is written to file `exports/notes.md`

`@input file: myfiles/note (output=variable:note)`  
The contents of `myfiles/note.md` is written to variable `note`

`@input file: notes/* (output=variable: all_notes)`  
The contents of all files in `notes` folder is written to variable `all_notes`. Since `write_mode` is not specified, default action is `append` - all files are concatenated into the one variable.

`@input file: notes/* (output=variable: note, write_mode=new)`  
Same as above, but with `write_mode=new`, each file in folder `notes` is written to its own variable (`notes_000`, `notes_001`, `notes_002`, etc).

`@tools web_search_duckduckgo (output=variable:search_result, write_mode=new)`  
All `web_search_duckduckgo` tool output is written to a variable, same sequential numbering pattern as above.

