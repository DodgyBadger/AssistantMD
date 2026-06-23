# 0021 - Keep Provider Reasoning Transient By Default

## Status

Accepted.

## Context

Some model providers expose reasoning or thinking artifacts as provider-native
message parts. Pydantic AI represents these as `ThinkingPart` entries inside
assistant `ModelResponse` messages. Persisting those parts in canonical chat
history means they are replayed on later turns.

That creates two problems. First, reasoning parts can add recurring token cost
without improving the user's durable conversation record. Second, provider
reasoning formats are not portable: a session that contains reasoning output
from one provider may fail or behave unpredictably when replayed through a
different provider.

Users may still want to inspect thinking output during a live turn, especially
for long or tool-heavy runs, and advanced users may intentionally choose to keep
provider-native reasoning artifacts.

## Decision

Provider reasoning and thinking parts are transient by default. AssistantMD may
stream them to the UI during the current turn, but durable chat persistence
removes `ThinkingPart` entries from assistant responses unless the user enables
`persist_model_reasoning_parts`.

When `persist_model_reasoning_parts=true`, AssistantMD stores provider-native
reasoning parts with the rest of the assistant response and treats existing
stored sessions containing reasoning parts as intentionally persisted provider
history.

## Rationale

Canonical chat history should preserve the user-visible conversation and the
provider-native parts required to continue it, not every provider-private
intermediate artifact. Making reasoning transient by default keeps replay
history smaller, reduces repeated token spend, and makes it more reliable to
switch an existing session between providers.

Keeping an explicit opt-in setting preserves escape hatches for users who value
durable reasoning artifacts more than portability or token efficiency.

## Consequences

- Live thinking output can be displayed while a response is streaming without
  becoming part of the default durable transcript.
- New sessions are more portable across providers because persisted history is
  less likely to contain provider-specific reasoning parts.
- Token usage on later turns is lower because prior reasoning artifacts are not
  replayed by default.
- Users who opt into `persist_model_reasoning_parts` accept higher token use and
  less portable chat history.
- Existing sessions that already contain reasoning parts remain replayed as
  stored data; AssistantMD does not add a separate read-time sanitizer for old
  history.

## Evidence

- Current contract: `docs/architecture/chat-sessions.md`
- Implementation plan: `IMPLEMENTATION_PLAN_REASONING_HISTORY_POLICY.md`
