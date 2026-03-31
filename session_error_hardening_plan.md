# Session Error Hardening Plan

## Goal

Ensure chat-session failures leave behind useful `system/activity.log` evidence even when a request fails before normal chat history is persisted.

## Scope

- Add structured chat session lifecycle logging around API entry, chat execution start, success, and failure.
- Capture stable failure metadata:
  - `session_id`
  - `vault_name`
  - `model`
  - selected tools
  - streaming vs non-streaming
  - execution phase
  - exception type
  - traceback
- Add deterministic validation coverage for forced chat failure logging.
- Cover both non-streaming and streaming failure paths.

## Constraints

- Do not change public request/response contracts unless needed for error safety.
- Keep scope on observability and session hardening, not unrelated chat behavior.
- Avoid full validation-suite execution; use targeted local checks only.

## Implementation Steps

1. Add shared exception-formatting and lifecycle logging helpers for chat execution.
2. Instrument `/api/chat/execute` and chat executor paths with structured start/success/failure records.
3. Add a validation scenario that forces a chat execution failure and verifies the activity log contains the failure context.
4. Run targeted local smoke checks for the forced failure path.

## Status

- [completed] Trace chat/session failure boundaries
- [completed] Implement structured failure logging
- [completed] Add validation coverage
- [completed] Run targeted smoke checks

## Verification

- `python -m py_compile api/endpoints.py api/utils.py core/llm/chat_executor.py validation/scenarios/integration/core/chat_failure_logging.py`
- `python -m py_compile validation/scenarios/integration/core/chat_stream_failure_logging.py`
- Targeted validation scenario passed:
  - `validation/scenarios/integration/core/chat_failure_logging.py`
  - `validation/scenarios/integration/core/chat_stream_failure_logging.py`
