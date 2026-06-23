# Reasoning History Persistence Policy Plan

## Goal

Make provider reasoning/thinking artifacts transient by default so chat history
stays portable across model providers and does not accumulate unnecessary replay
tokens.

## Current Problem

Pydantic AI can represent provider reasoning output as `ThinkingPart` entries
inside `ModelResponse` messages. AssistantMD currently persists provider-native
messages directly into `system/chat_sessions.db` and later replays effective
history into the next chat run. A DeepSeek-originated reasoning part can
therefore be replayed into an OpenAI Responses request, where it is treated as
an OpenAI reasoning item and rejected.

This also risks recurring token waste when reasoning summaries or raw reasoning
metadata are carried forward across turns.

## User-Facing Contract

- Add a general setting, tentatively `persist_model_reasoning_parts`.
- Default: `false`.
- When `false`, AssistantMD receives reasoning/thinking parts for the live turn
  but does not persist them in durable chat history.
- When `true`, AssistantMD preserves reasoning/thinking parts in stored
  provider-native history with a settings description warning that this can
  increase token usage and make history less portable between providers.
- Existing visible assistant text, user messages, tool calls, tool returns, and
  attachments remain persisted and replayable.

## Affected Areas

- `core/chat/chat_store.py`
  - Add a small message sanitizer used before `add_messages(...)` and
    `replace_session_messages(...)` serialize messages.
  - Apply the same write-boundary policy to compaction checkpoint replacement
    history because it becomes the effective replay history after compaction.
  - Remove `ThinkingPart` from `ModelResponse.parts` when the new setting is
    disabled.
  - Preserve normal role/text extraction behavior.
- `core/chat/executor.py`
  - No replay-time sanitizer. Effective history loaded from the database remains
    the source of truth for model replay.
- `core/settings/settings.template.yaml`
  - Add the user-editable general setting under the Chat category.
- `core/settings/__init__.py` or a nearby typed settings helper
  - Add a helper such as `get_persist_model_reasoning_parts()`.
- `docs/architecture/chat-sessions.md`
  - Document that durable history excludes reasoning parts by default and that
    the setting can opt into provider-native persistence.
- `docs/architecture/settings-secrets.md`
  - List the new general setting.

## Validation Target

Extend or add an integration scenario under
`validation/scenarios/integration/core/` that constructs chat history containing
a `ModelResponse` with `ThinkingPart` and verifies:

- default persistence removes `ThinkingPart` from stored/effective history;
- setting `persist_model_reasoning_parts=true` preserves `ThinkingPart` in stored
  history;
- visible `TextPart` and tool call/return parts survive unchanged.

The scenario should use deterministic Pydantic AI message objects and not call
real providers.

## Implementation Notes

- Do not mutate caller-owned message objects in place. Return copied
  `ModelResponse` objects with filtered `parts`.
- Use Pydantic AI message types directly rather than JSON string manipulation.
- Keep the sanitizer narrow: remove only `ThinkingPart` unless future evidence
  identifies another provider-private part type.
- Apply sanitization only at write boundaries. Chat replay should send exactly
  the effective history stored in the database.
- Avoid migration of existing rows in this slice. Existing chat sessions that
  already contain reasoning parts behave as if `persist_model_reasoning_parts`
  had been enabled when those turns were saved.

## Next Phase

Move to Feature Development after this plan: implement the setting/helper,
sanitizers, docs updates, and focused validation scenario.
