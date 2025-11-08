# Pattern Variables Reference

The AssistantMD supports various pattern variables for dynamic file paths and headers. Patterns are used in `@output-file`, `@input-file`, and `@header` directives.

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

Files are tracked by content hash, so:
- Renaming or moving a file doesn't mark it as unprocessed
- Editing a file's content marks it as unprocessed (will be re-processed)
- State is tracked per assistant and per pattern

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