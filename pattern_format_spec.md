# Pattern Format Spec (Draft)

## Goal
Add explicit, optional date formatting to time-based patterns without changing existing defaults. Example: `{today:YYYYMMDD}`.

## Non-Goals
- No automatic filename date parsing in this phase.
- No behavior changes when no explicit format is provided.

## Supported Patterns (Existing)
Time-based patterns should accept optional format:
- `{today}`
- `{yesterday}`
- `{tomorrow}`
- `{this-week}`
- `{last-week}`
- `{next-week}`
- `{this-month}`
- `{last-month}`

Name-based patterns can also accept format if desired later, but not required for MVP:
- `{day-name}`
- `{month-name}`

## Format Tokens (Custom, no strftime)
Date tokens:
- `YYYY` → 4-digit year (2026)
- `YY` → 2-digit year (26)
- `MM` → 2-digit month (01–12)
- `M` → month number (1–12)
- `DD` → 2-digit day (01–31)
- `D` → day number (1–31)

Month name tokens:
- `MMMM` → full month name (January)
- `MMM` → short month name (Jan)

Weekday name tokens:
- `dddd` → full weekday (Monday)
- `ddd` → short weekday (Mon)

Optional time tokens (defer if not needed):
- `HH` → 24-hour (00–23)
- `mm` → minutes (00–59)
- `ss` → seconds (00–59)

## Examples
- `{today:YYYYMMDD}` → `20260210`
- `{today:YYYY-MM-DD}` → `2026-02-10`
- `{today:MMMM DD, YYYY}` → `February 10, 2026`
- `{day-name:ddd}` → `Tue`
- `{this-week:YYYYMMDD}` → week start date formatted (same semantics as current `{this-week}`)
- `{this-month:YYYYMM}` → `2026-02` or `202602` depending on format

## Semantics
- If no format is specified, use existing behavior:
  - Date patterns: `YYYY-MM-DD`
  - Month patterns: `YYYY-MM`
  - Day/month name patterns: existing name output
- For `{this-week}` and related week patterns, format the **week start date** (current behavior).
- For `{this-month}`, format the **first day of the month** if a day component is requested, otherwise just the month/year (as today’s behavior).

## Implementation Plan (High Level)
1. Update `PatternUtilities.resolve_date_pattern()` to parse optional `:<format>` suffix.
   - Example input: `today:YYYYMMDD`.
2. Add a small formatter that converts a `datetime` to the custom token format.
   - Replace tokens in order of length (e.g., `YYYY` before `YY`, `MMMM` before `MMM`).
3. Keep output unchanged when no format is supplied.
4. Add tests for:
   - `{today:YYYYMMDD}`
   - `{today:MMMM DD, YYYY}`
   - `{this-week:YYYYMMDD}`
   - `{this-month:YYYYMM}`

## Notes
- This is explicit, opt-in formatting only; no auto-detect or filename parsing changes.
- Later extension: allow `{today:auto}` or a config flag to enable filename matching for inputs.
