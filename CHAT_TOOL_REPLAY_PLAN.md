# Chat Tool Replay Plan

## Problem

Cancelled, failed, or timed-out chat turns can leave persisted diagnostic tool-event rows even when the assistant/tool messages from that attempt are not committed to canonical chat history. The current session replay path also pairs persisted tool events to rendered assistant messages by queue order. That makes the display fragile: stale events can appear under a later assistant reply, and valid current-turn tool calls can be hidden or shown under the wrong message.

This can confuse users into thinking tools ran when they did not, or that file edits landed when the underlying tool result was from a different attempt.

## Contract

- Pydantic AI `AgentRunResult.new_messages()` is the canonical commit payload for a completed chat turn.
- Pydantic AI `ModelRequest` / `ModelResponse` JSON in `chat_messages` is the durable source of truth for chat history.
- Pydantic AI `ToolCallPart.tool_call_id` and `ToolReturnPart.tool_call_id` are the authoritative relationship between tool calls and tool returns.
- `chat_tool_events` are diagnostic/display enrichment only. They must never become canonical history and must not be replayed unless their `tool_call_id` appears in committed Pydantic messages.
- Live streaming events are UI progress hints. They do not become committed history until the run reaches `AgentRunResultEvent`.
- Execution tasks own lifecycle status and cancellation state. Chat executor/store own chat-history commit semantics.

## Scope

- `core/chat/executor.py`
  - Confirm success, cancellation, usage-limit, timeout, and provider-error paths only commit assistant/tool messages after `AgentRunResultEvent`.
  - Keep execution task metadata useful for diagnosing failed attempts.

- `core/chat/chat_store.py`
  - Keep committed Pydantic messages as the canonical transcript.
  - Provide helpers that extract committed tool-call and tool-return IDs from stored message JSON.
  - Preserve raw diagnostic tool-event reads for lower-level debugging.

- `api/services.py` and `api/models.py`
  - Expose enough structured per-message tool metadata for the UI to associate tool events by `tool_call_id`, not queue order.
  - Continue hiding orphan diagnostic tool events from transcript-facing session detail.

- `static/js/chat-rendering.js`
  - Replace queue-order tool-event replay with ID-based replay.
  - Ignore orphan diagnostic events in persisted session rendering.
  - Avoid rendering empty assistant bubbles for unmatched tool events.

- `core/chat/history_service.py` and `core/tools/session_ops.py`
  - Ensure session tools and summary extraction see committed history and committed tool events only.

## Validation Target

Extend focused chat persistence coverage rather than relying only on manual UI testing:

- Completed turn with one tool call shows the correct committed tool event.
- Completed turn with multiple tool calls shows each tool under the correct assistant message.
- A cancelled/failed attempt with orphan `chat_tool_events`, followed by a successful turn, does not display stale tools under the successful reply.
- Session detail payload includes committed tool IDs in a way the frontend can replay deterministically.

Use `validation/scenarios/integration/core/chat_session_persistence_contract.py` if its existing follow-up-chat failure is repaired first. Otherwise add a narrower scenario or store/API smoke that isolates session detail replay from unrelated context assembly failures.

## Current State

Commit `dd72b04` added a guardrail: transcript-facing tool-event reads use committed `tool_call_id`s only. That reduces orphan leakage but does not fully fix queue-order replay. The next implementation should either keep that guard as part of the broader fix or replace it with a clearer committed-tool exchange helper.

The current implementation exposes committed `tool_call_ids` and `tool_return_ids` on each session-detail message, preserving Pydantic message part order. Persisted session rendering now groups tool events by `tool_call_id` and attaches only events whose IDs appear in the skipped committed tool messages. Orphan diagnostic events no longer create empty assistant bubbles or shift the event queue.

## Next Steps

1. Manually smoke the chat UI on a live or representative session that previously showed stale tool calls.
2. Decide whether this root plan should be deleted before merge or kept until the PR lands.
3. Investigate the separate `chat_session_persistence_contract` follow-up-chat failure if it is still present.
