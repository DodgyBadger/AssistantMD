# History Processor Briefing

## Summary

We hit a chat-stream failure when the model read several PNG files via `file_ops_safe(read)` and then continued the same tool-using turn. The OpenAI Responses API rejected the follow-up request with:

- `No tool call found for function call output with call_id ...`

This was not a general "tools are broken" issue. The failure surfaced when multimodal tool returns were present and the chat context manager rebuilt message history before the next model request.

## What We Confirmed

- Our chat context manager is attached through PydanticAI's `HistoryProcessor` capability.
- `HistoryProcessor` is hardwired to run `before_model_request`, which means it runs before every model request, not once per user turn.
- A single user turn can produce multiple model requests when tools are involved.
- Our default context template (`system/Authoring/default.md`) rebuilds history through `memory_ops`, which normalizes messages into role/content form.
- That normalization is lossy for provider-native tool messages, especially multimodal tool returns.
- PydanticAI's docs are explicit that tool calls and tool returns must remain correctly paired when history is sliced, summarized, or rebuilt.

## Why The PNG Case Failed

The likely sequence was:

1. User asked the chat model to inspect several PNG files in the vault.
2. The model called `file_ops_safe(read)` multiple times.
3. Those calls succeeded and produced multimodal tool returns.
4. The agent prepared the next model request in the same run.
5. The `HistoryProcessor` ran again and rebuilt history.
6. The rebuilt history did not preserve the provider-native tool-call/tool-return structure faithfully enough.
7. OpenAI Responses received a tool output without the exact matching tool call chain and returned HTTP 400.

## Important Architectural Point

There are two separate concerns:

### 1. Correctness

When tool parts are present in the history sent to the provider, the history must remain protocol-valid.

Safe patterns:

- preserve complete tool exchanges exactly
- remove complete tool exchanges together
- replace old regions with a clean summary that contains no raw tool artifacts

Unsafe pattern:

- preserve or recreate only part of a tool exchange

### 2. Cost / latency

If a context script uses `generate()`, it may rerun multiple times per user turn because `HistoryProcessor` is per-model-request.

This is a separate problem from the 400 error.

Likely mitigation:

- use `generate(cache=...)` correctly for expensive context synthesis

## Current Patch

The current branch includes a narrow guard:

- if the active in-flight turn already contains `tool-call` or `tool-return` parts, the context manager stops rebuilding that turn and passes the provider-native message history through unchanged

This fixes the immediate correctness issue for the in-flight tool loop and passed targeted validation.

This patch should be treated as a short-term correctness guard, not necessarily the final architecture. Once grouped tool-exchange policy is implemented in `memory_ops` and the default context-template path is updated to rely on that safer abstraction, we should reexamine whether the passthrough guard is still needed or can be narrowed further.

## Why This Is Not The Full Design Decision

The current patch does **not** answer the broader policy question:

- how should we reshape older history that contains tool parts?

The in-flight turn is the highest-risk case, but prior history can also break provider expectations if we summarize or slice it carelessly.

## Working Design Direction

The most promising boundary is:

- `ChatStore` / internal runtime APIs keep raw provider-native messages.
- `memory_ops` is treated as an LLM-facing abstraction, not a raw protocol inspector.

That means `memory_ops` should be free to expose safer logical history units than the underlying provider-native message sequence.

### Proposed `memory_ops` policy

For LLM-facing history access, a tool-call/tool-return pair should be treated as one logical unit.

Implications:

- context scripts should not see half of a tool exchange by default
- summarization / trimming / filtering logic can operate on whole tool exchanges
- if some lower-level system needs raw individual provider messages, it should use a lower-level internal interface rather than `memory_ops`

This would make `memory_ops` a safer abstraction for context templates and reduce the chance of future invalid-history bugs.

## Decision Needed Before Merge

We should explicitly decide on the following policy:

1. Active in-flight tool turns must preserve provider-native tool parts exactly when building requests sent back to the provider.
2. `memory_ops` should be treated as an LLM-facing abstraction and should group tool-call/tool-return pairs into a single logical exchange for context-script consumption.
3. Older tool-containing history may be reshaped only at the level of whole logical exchanges or by replacing older spans with summary messages that contain no raw tool artifacts.
4. Context scripts that use `generate()` for summary/context synthesis should use caching so they do not rerun expensively on every model request.

## Open Questions

- Should we keep the current in-flight passthrough patch as-is until `memory_ops` grouping lands?
- Should `memory_ops.get_history()` default to grouped logical exchanges for chat context templates?
- Should grouped exchange access be the only LLM-facing mode, with raw message access reserved for lower-level internal APIs?
- Should the default context template stop rehydrating full normalized history until `memory_ops` grouping semantics are in place?
- Should expensive context synthesis be moved behind explicit cached artifacts instead of being recomputed in a history processor?
