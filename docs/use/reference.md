# Reference


## Directives

| Name | Description | Applies To | Example | Notes |
| --- | --- | --- | --- | --- |
| `@output-file` | Write step output to a specific file. | Workflow | `@output-file reports/{today}` | Auto-adds `.md` if missing. Avoid mixing with `file_ops_safe` in the same step. |
| `@input-file` | Inline file content or paths as additional context. | Workflow, Context Template | `@input-file notes/*.md` | Supports `(required)` and `(paths-only)` options; patterns/globs allowed. |
| `@header` | Prepend a level-1 heading to the output file. | Workflow | `@header Weekly Review` | Only used when `@output-file` is present. Supports patterns. |
| `@model` | Override the model for a step. | Workflow, Context Template | `@model gpt-mini` | Context template defaults to chat model. |
| `@write-mode` | Control how output files are written. | Workflow | `@write-mode append` | `append` (default) or `new` (numbered files). |
| `@run-on` | Limit which days a step runs. | Workflow | `@run-on monday, friday` | Works with scheduled workflows; `daily` and `never` supported. |
| `@tools` | Enable tools for a step. | Workflow, Context Template | `@tools file_ops_safe` | Names must match tool IDs from the UI. |
| `@cache` | Cache a context step output for reuse. | Context Template | `@cache 24h` | Values: `session`, `daily`, `weekly`, or duration `30s/10m/2h/1d`. Invalidates on template edit. Gating directives override cache. |
| `@token-threshold` | Only run the step if estimated history tokens exceed the threshold. | Context Template | `@token-threshold 4000` | Skips the step if below threshold (no cache reuse). |
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
| `description` | Human-readable description. | Workflow, Context Template | `description: Daily planning` | For documentation only. |
| Custom fields | Any extra metadata. | Workflow, Context Template | `team: ops` | Ignored by the runtime. |

## Patterns

| Name | Description | Applies To | Example | Notes |
| --- | --- | --- | --- | --- |
| `{today}` | Current date (YYYY-MM-DD). | `@input-file`, `@output-file`, `@header` | `@output-file daily/{today}` | Time-based pattern. |
| `{yesterday}` | Previous day date. | `@input-file`, `@output-file`, `@header` | `@output-file daily/{yesterday}` | Time-based pattern. |
| `{tomorrow}` | Next day date. | `@input-file`, `@output-file`, `@header` | `@output-file daily/{tomorrow}` | Time-based pattern. |
| `{this-week}` | Current week start date. | `@input-file`, `@output-file`, `@header` | `@output-file reports/{this-week}` | Respects `week_start_day`. |
| `{last-week}` | Previous week start date. | `@input-file`, `@output-file`, `@header` | `@output-file reports/{last-week}` | Respects `week_start_day`. |
| `{next-week}` | Next week start date. | `@input-file`, `@output-file`, `@header` | `@output-file reports/{next-week}` | Respects `week_start_day`. |
| `{this-month}` | Current month (YYYY-MM). | `@input-file`, `@output-file`, `@header` | `@output-file archive/{this-month}` | Time-based pattern. |
| `{last-month}` | Previous month (YYYY-MM). | `@input-file`, `@output-file`, `@header` | `@output-file archive/{last-month}` | Time-based pattern. |
| `{day-name}` | Current day name. | `@input-file`, `@output-file`, `@header` | `@header {day-name} Review` | Name-based pattern. |
| `{month-name}` | Current month name. | `@input-file`, `@output-file`, `@header` | `@header {month-name} Plan` | Name-based pattern. |
| `{latest}` | Most recent file or folder by date in name. | `@input-file` | `@input-file journal/{latest}` | Use `{latest:N}` for N most recent files. |
| `{pending}` | Unprocessed files for a workflow pattern. | `@input-file` | `@input-file tasks/{pending:5}` | Per-workflow tracking; files re-queue on edits. |
| Glob patterns | Match files by wildcard. | `@input-file` | `@input-file notes/*.md` | Recursive `**` and parent `..` are not allowed. |
