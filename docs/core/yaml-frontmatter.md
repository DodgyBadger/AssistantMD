# YAML Frontmatter Configuration

All assistant configuration is specified in YAML frontmatter at the top of the file, enclosed by `---` delimiters. If you are working in Obsidian, these will appear as properties.

**Quote Handling**: Quotes around values are optional and handled automatically. Obsidian's property editor adds quotes around values with special characters (like `schedule: "cron: 0 8 * * *"`), but you can omit them when editing raw markdown (like `schedule: cron: 0 8 * * *`). Both formats work identically.

## Required Parameters

**workflow** (string, required)
- The workflow engine to use for this assistant
- Currently supported: `step`, `interactive`

## Optional Parameters

**schedule** (string, optional)
- Defines when the assistant runs using crontab format or explicit datetime
- If omitted, assistant is manual-only (executed via API or interactive interface)
- **Note**: Quotes are optional. Both `schedule: cron: 0 8 * * *` and `schedule: "cron: 0 8 * * *"` work identically. Obsidian automatically adds quotes when editing properties, but they're not required when editing raw markdown.

### Recurring Schedules

Use standard 5-field crontab syntax with `cron:` prefix:

```yaml
schedule: cron: 0 8 * * *              # Daily at 8am
schedule: cron: 0 9 * * 1-5            # Weekdays at 9am
schedule: cron: */30 9-17 * * *        # Every 30 minutes, 9am-5pm
schedule: cron: 0 9 1,15 * *           # 1st and 15th of month at 9am
```

**Crontab Resources**:
- [crontab.guru](https://crontab.guru) - Interactive crontab expression tester
- [Crontab format reference](https://en.wikipedia.org/wiki/Cron)

### One-Time Schedules

Use explicit datetime with `once:` prefix:

```yaml
schedule: once: 2025-12-25 10:00       # Christmas 2025 at 10am
schedule: once: 2026-01-15 14:30       # Specific date and time
```

**Supported Formats**:
- `once: 2025-12-25 10:00` - ISO format (recommended)
- `once: 2025-12-25T10:00:00` - ISO with seconds
- `once: December 25, 2025 at 10am` - Natural language
- `once: 2025-12-25` - Date only (defaults to 9am)

**Important**: Times must be explicit and in the future. No relative terms allowed (`tomorrow`, `next week`, etc.).

**enabled** (boolean, optional, default: true)
- Whether this assistant is active and should run on schedule
- Only affects scheduled execution - manual execution always works regardless of this setting
- Set to `false` to temporarily pause scheduled runs without deleting the assistant

**week_start_day** (string, optional, default: "monday")
- Defines which day of the week is considered the start for weekly patterns
- Valid values: `monday`, `tuesday`, `wednesday`, `thursday`, `friday`, `saturday`, `sunday`
- Affects `{this-week}`, `{last-week}`, `{next-week}` patterns

**description** (string, optional)
- Human-readable description of what this assistant does
- For user documentation only. Has no functional impact on the assistant.

## Custom Parameters

You may include other parameters / properties for your own use and categorization. Anything not recognized as the required or optional assistant parameters described above will be ignored.

## Example

```yaml
---
schedule: cron: 0 8 * * *
workflow: step
enabled: true
week_start_day: monday
description: Daily planning assistant that reviews goals and creates task lists
---
```
