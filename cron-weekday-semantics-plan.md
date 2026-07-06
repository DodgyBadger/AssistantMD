# Cron Weekday Semantics Implementation Plan

## Objective

Make the APScheduler 3.x numeric day-of-week discrepancy visible to users
without changing existing schedule behavior.

## Plan

- [x] Keep `parse_cron_schedule()` behavior unchanged so existing persisted and
  authored schedules continue to use APScheduler 3.x semantics.
- [x] Document weekday-name cron schedules as the recommended authoring style.
- [x] Add explicit conversion helpers for preserving schedule meaning between
  standard cron and APScheduler 3.x numeric weekday semantics.
- [x] Run targeted smoke checks for helper conversions and current parser
  behavior.
