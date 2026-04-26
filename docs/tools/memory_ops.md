# `memory_ops`

## Purpose

Read structured conversation history through the core memory service.

This tool is currently disabled by default. Prefer the authoring `retrieve_history(...)` helper inside context scripts.

## Parameters

- `operation`: required. Supported values are `get_history` and `get_tool_events`.
- `scope`: optional. Currently `session`.
- `session_id`: optional explicit session id.
- `limit`: optional positive integer or `all`.
- `message_filter`: optional for `get_history`. One of `all`, `exclude_tools`, or `only_tools`.

## Notes

- `get_history` returns canonical ordered message history from the memory service.
- `get_tool_events` is for explicit inspection of structured tool activity.
