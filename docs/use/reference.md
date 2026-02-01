# Reference


## Directives

| Name | Description | Applies To | Example | Notes |
| --- | --- | --- | --- | --- |
| `@output` | Write step output to a specific file or buffer. | Workflow | `@output file: reports/{today}` | Auto-adds `.md` if missing. Avoid mixing with `file_ops_safe` in the same step. |
| `@input` | Inline file content or buffer content as additional context. | Workflow, Context Template | `@input file: notes/*.md` | Supports `(required)`, `(refs-only)` and routing parameters. |
| `@header` | Prepend a level-1 heading to the output file. | Workflow | `@header Weekly Review` | Only used when `@output` is present. Supports patterns. |
| `@model` | Override the model for a step. | Workflow, Context Template | `@model gpt-mini` | Use `@model none` to skip LLM execution for the step/section. |
| `@write-mode` | Control how output files are written. | Workflow | `@write-mode append` | `append` (default), `replace`, or `new` (numbered files). |
| `@run-on` | Limit which days a step runs. | Workflow | `@run-on monday, friday` | Works with scheduled workflows; `daily` and `never` supported. |
| `@tools` | Enable tools for a step. | Workflow, Context Template | `@tools file_ops_safe` | Names must match tool IDs from the UI. Per-tool params are supported (see Routing). |
| `@cache` | Cache a context step output for reuse. | Context Template | `@cache 24h` | Values: `session`, `daily`, `weekly`, or duration `30s/10m/2h/1d`. Invalidates on template edit. Gating directives override cache. |
| `@recent-runs` | Control how many recent runs are available to the step. | Context Template | `@recent-runs 3` | Use `all` for full history, `0` for none. |
| `@recent-summaries` | Control how many prior context manager outputs are available. | Context Template | `@recent-summaries 1` | Use `all` for all prior outputs. |

## Frontmatter

| Name | Description | Applies To | Example | Notes |
| --- | --- | --- | --- | --- |
| `workflow_engine` | Select the workflow engine. | Workflow | `workflow_engine: step` | Required for workflows. Currently only `step`. |
| `schedule` | Define when the workflow runs. | Workflow | `schedule: "cron: 0 9 * * *"` | Omit for manual-only. Supports `cron:` and `once:`. |
| `enabled` | Enable scheduled runs. | Workflow | `enabled: false` | Affects scheduled runs only. Manual runs still work. |
| `week_start_day` | Choose the week start used by patterns. | Workflow, Context Template | `week_start_day: monday` | Defaults to monday. |
| `passthrough_runs` | How many recent runs are passed to the chat agent. | Context Template | `passthrough_runs: 3` | Use `all` for full history or `0` for summary-only. |
| `token_threshold` | Only run the context manager when history exceeds this token estimate. | Context Template | `token_threshold: 4000` | When below threshold, the full passthrough history is used. |
| `description` | Human-readable description. | Workflow, Context Template | `description: Daily planning` | For documentation only. |
| Custom fields | Any extra metadata. | Workflow, Context Template | `team: ops` | Ignored by the runtime. |

## Patterns

| Name | Description | Applies To | Example | Notes |
| --- | --- | --- | --- | --- |
| `{today}` | Current date (YYYY-MM-DD). | `@input`, `@output`, `@header` | `@output file: daily/{today}` | Time-based pattern. |
| `{yesterday}` | Previous day date. | `@input`, `@output`, `@header` | `@output file: daily/{yesterday}` | Time-based pattern. |
| `{tomorrow}` | Next day date. | `@input`, `@output`, `@header` | `@output file: daily/{tomorrow}` | Time-based pattern. |
| `{this-week}` | Current week start date. | `@input`, `@output`, `@header` | `@output file: reports/{this-week}` | Respects `week_start_day`. |
| `{last-week}` | Previous week start date. | `@input`, `@output`, `@header` | `@output file: reports/{last-week}` | Respects `week_start_day`. |
| `{next-week}` | Next week start date. | `@input`, `@output`, `@header` | `@output file: reports/{next-week}` | Respects `week_start_day`. |
| `{this-month}` | Current month (YYYY-MM). | `@input`, `@output`, `@header` | `@output file: archive/{this-month}` | Time-based pattern. |
| `{last-month}` | Previous month (YYYY-MM). | `@input`, `@output`, `@header` | `@output file: archive/{last-month}` | Time-based pattern. |
| `{day-name}` | Current day name. | `@input`, `@output`, `@header` | `@header {day-name} Review` | Name-based pattern. |
| `{month-name}` | Current month name. | `@input`, `@output`, `@header` | `@header {month-name} Plan` | Name-based pattern. |
| `{latest}` | Most recent file or folder by date in name. | `@input` | `@input file: journal/{latest}` | Use `{latest:N}` for N most recent files. |
| `{pending}` | Unprocessed files for a workflow pattern. | `@input` | `@input file: tasks/{pending:5}` | Per-workflow tracking; files re-queue on edits. |
| Glob patterns | Match files by wildcard. | `@input` | `@input file: notes/*.md` | Recursive `**` and parent `..` are not allowed. |

## Buffers

Buffers are run-scoped in-memory variables addressed with the `variable:` scheme. They can be used anywhere file inputs/outputs are supported.

Examples:
- `@output variable: summary_buffer`
- `@input variable: summary_buffer`

## Routing

Routing redirects directive or tool outputs to a destination instead of inlining content.

### Destinations
- `inline` (default)
- `variable: NAME`
- `file: PATH`
- `discard`

### @input routing
Attach `output=...` to `@input` to route the resolved content (or references when `refs-only` is set).

Examples:
- `@input file: notes/*.md (output=variable: notes_buffer)`
- `@input file: notes/*.md (refs-only, output=variable: notes_refs)`
- `@input variable: notes_buffer (output=file: exports/notes)`

### Tool routing
Attach `output=...` per tool token in `@tools`. Optional `write-mode=append|replace|new` is supported.

Examples:
- `@tools file_ops_safe(output=variable: tool_buffer)`
- `@tools file_ops_safe(output=file: tool-outputs/listing, write-mode=replace)`
- `@tools file_ops_safe(output=inline)`
