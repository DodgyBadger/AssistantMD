# Transient Thinking UI Plan

## Goal

Make live model thinking output intentional in the chat UI without persisting it
as normal assistant response text or replay history.

## Current Behavior

- Chat execution currently emits UI `delta` events only for Pydantic AI
  `TextPart` and `TextPartDelta`.
- `ThinkingPart` and `ThinkingPartDelta` are not handled explicitly.
- The browser appends every `delta` payload to the active assistant message.
- After completion, the app reloads the session from persisted history.
- Persisted session rendering uses `content_text`, which only includes visible
  assistant `TextPart` content.

This means any reasoning-like content that arrives as text can appear during
streaming and disappear after the persisted session reloads, but the behavior is
not represented as a stable UI contract.

## Proposed Contract

- Backend emits explicit transient thinking events for Pydantic AI
  `ThinkingPart` and `ThinkingPartDelta`.
- Normal answer text continues to use existing `delta` events.
- Frontend renders thinking events inline before answer text in the active
  assistant bubble using italic text and a lighter color.
- Frontend also renders ordinary streamed assistant text as provisional working
  text until the turn proves it is final answer text. If a tool call starts, the
  provisional text stays transient because persisted session rendering treats
  tool-call messages as tool activity rather than final assistant answers. If no
  tool call starts, the provisional text is promoted to normal answer text on
  completion.
- The transient thinking text disappears on completion by default when the
  session reloads from persisted history.
- Thinking events are not persisted as assistant `content_text`.
- When `persist_model_reasoning_parts` is enabled and a session contains stored
  `ThinkingPart` values, session detail renders those parts with the same
  thinking style before the assistant answer.
- If a provider streams reasoning-like content as ordinary `TextPartDelta`, the
  app does not infer semantics from the text itself; the provisional/final
  styling follows the stream lifecycle and tool events.

## Affected Areas

- `core/chat/task_execution.py`
  - Import and handle `ThinkingPart` / `ThinkingPartDelta`.
  - Add `thinking_delta` event payloads, preserving task sequence semantics.
- `static/app.js`
  - Route `thinking_delta` events separately from answer `delta` events.
- `static/js/chat-rendering.js`
  - Add transient thinking text state to streaming assistant messages.
  - Render thinking text inline with a dedicated span/class while streaming.
  - Keep pre-tool streamed answer text in a provisional transient style from the
    first delta, promoting it to normal answer text only for no-tool turns.
- `api/services.py`
  - Convert persisted `ThinkingPart` values into styled display content only for
    session detail responses when those parts exist in stored model messages.
- `validation/scenarios/integration/core/`
  - Extend a task-event streaming scenario or add a focused scenario with a fake
    agent that emits `ThinkingPartDelta` followed by normal text.

## Validation Target

- Backend SSE stream contains `thinking_delta` for `ThinkingPartDelta`.
- Normal `TextPartDelta` still appears as `delta`.
- A completed session reload does not include thinking content by default.
- A completed session reload does include styled thinking content when reasoning
  persistence is enabled for that session.
- Tool event rendering remains unchanged.
- Text streamed before a tool call is visually transient rather than styled as
  final assistant answer text.
- No-tool responses still settle as normal assistant answer text at completion.

## Notes

- Pydantic AI already exposes `previous_part_kind` on `PartStartEvent`, which
  can help group consecutive thinking parts if needed later.
- No schema change is required for transient display.
- This is independent of `persist_model_reasoning_parts`; that setting controls
  durable history, not live UI display.
