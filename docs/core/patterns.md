# Pattern Variables Reference

AssistantMD supports pattern variables for dynamic file paths and headers. Patterns are used in `@output-file`, `@input-file`, and `@header` directives.

## Time-Based Patterns

**Date Patterns**
- `{today}` - Current date (YYYY-MM-DD)
- `{yesterday}` - Previous day date
- `{tomorrow}` - Next day date

**Week Patterns**
- `{this-week}` - Current week start date (respects week_start_day setting)
- `{last-week}` - Previous week start date
- `{next-week}` - Next week start date

**Month Patterns**
- `{this-month}` - Current month (YYYY-MM)
- `{last-month}` - Previous month

**Name Patterns**
- `{day-name}` - Current day name (e.g., Monday, Tuesday)
- `{month-name}` - Current month name (e.g., January, September)

## File Collection Patterns (@input-file only)

**Latest File Patterns**
- `{latest}` - Most recent file by date
- `{latest:N}` - N most recent files by date

**Stateful Processing Patterns**
- `{pending}` - Unprocessed files (oldest first, default limit 10)
- `{pending:N}` - Up to N oldest unprocessed files

How `{pending}` tracking works:
- Files are marked processed at the end of a step that used `{pending}`.
- A file is considered “already processed” on the next run if either its content hash matches a stored record **or** it has the same path and was not modified after it was marked processed. This prevents in-run edits (e.g., tagging) from re-queuing the same file, while still re-queuing later user edits.
- Renames without edits are skipped (hash match). Renames with edits are re-queued.
- State is tracked per workflow and per pattern (including the literal directive string).

What works well:
- Inbox-style processing where later edits should re-queue a file.
- In-place enrichment/tagging where the step edits the input file; those edits do not bounce the file back into pending.

What doesn’t work:
- “Once-and-done regardless of future edits” — later edits will still re-queue.
- Reusing `{pending}` multiple times in the same run to revisit the same file; once a step marks it processed, later `{pending}` steps in that run will skip it. Use explicit file references if a later step needs the same file.

**Glob Patterns**
- `*.md` - All .md files in vault root
- `folder/*.md` - All .md files in specific folder
- `prefix*.md` - All .md files starting with prefix
- `*-draft.md` - All .md files ending with -draft

## Examples

**Output File Patterns**
```markdown
@output-file planning/{today}          # Creates planning/2025-09-11.md
@output-file reports/{this-week}       # Creates reports/2025-09-09.md (Monday)
@output-file archive/{this-month}      # Creates archive/2025-09.md
```

**Input File Patterns**
```markdown
@input-file journal/{latest:3}         # Reads 3 most recent journal files
@input-file tasks/{pending:5}          # Reads next 5 unprocessed task files
@input-file notes/*.md                 # Reads all markdown files in notes folder
```
