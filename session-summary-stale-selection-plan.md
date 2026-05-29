# Session Summary Stale Selection Plan

## Scope

Update stale session-summary detection without changing the persisted data model.

## Policy

A session summary is pending when no summary exists. A stored summary is stale
when the current persisted chat message count differs from the message count
recorded in summary metadata at extraction time. Count increases cover appended
turns; count decreases cover compaction rewrites.

## Affected Areas

- `core/memory/session_summary_status.py`
- `core/authoring/helpers/retrieve_sessions.py`
- `core/tools/session_ops.py`
- `validation/scenarios/integration/core/retrieve_sessions_helper.py`
- session-summary authoring/tool documentation

## Validation Target

Extend the retrieve-sessions integration scenario to assert both positive and
negative message-count deltas are returned as stale.

## Next Steps

1. Remove grace-window and minimum-new-message checks from stale status.
2. Keep `message_count` summary metadata as the freshness marker.
3. Run the focused scenario and lightweight syntax checks.
