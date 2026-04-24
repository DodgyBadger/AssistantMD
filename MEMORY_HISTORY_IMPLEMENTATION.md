# Memory History Implementation

## Objective

Establish `core/memory` as the single broker for conversation history while separating policy by caller:

- `memory_ops` remains an LLM-facing retrieval tool and may serialize / flatten for inspection use.
- Monty/context assembly gets a stricter helper path that preserves safe history semantics and makes it difficult to break tool-call / tool-return fidelity accidentally.

## Problem Statement

We currently have a canonical provider-native chat history in `ChatStore`, but context templates access history indirectly through `call_tool("memory_ops", ...)`, which returns JSON text. Templates then parse and reshape those items before passing them into `assemble_context(...)`.

That path has two issues:

1. It round-trips through JSON even when the consumer is authored Python.
2. It makes flattening the default behavior for context assembly instead of an explicit choice.

This is especially dangerous when tool parts are present. The LLM-facing `memory_ops` contract may reasonably flatten history for inspection, but the context-manager path needs a safer abstraction.

## Decision

`core/memory` will be the broker of conversation history fidelity.

Caller policy will diverge:

- `memory_ops` is a generic LLM-facing tool adapter over the broker.
- A new Monty-facing history helper will be a structured adapter over the broker.
- `assemble_context(...)` will compose already-safe history objects; it should not infer proper message-history semantics from arbitrary flattened dicts.

## Current State

Implemented:

- `core/memory/service.py` is now the shared broker for conversation-history retrieval and tool-event retrieval.
- `memory_ops` uses that broker.
- `core/authoring/helpers/history/retrieve.py` now exposes broker-backed history directly to authored Python.
- `core/authoring/helpers/history/assemble.py` accepts broker-derived history units without forcing a JSON/text flattening step.
- `HistoryMessage`, `ToolExchange`, `ContextMessage`, and `RetrievedHistoryResult` expose clean prompt text through `text` while retaining provider-native fields for faithful assembly.
- the default context templates now use `retrieve_history(...)` instead of `call_tool("memory_ops", ...)`.
- the chat-visible `memory_ops` tool has been removed from settings while this helper path stabilizes.

Still in progress:

- tightening validation coverage around the new authoring helper surface
- deciding whether old tool-heavy history should later be compressed by explicit transforms

## Target Architecture

### 1. Broker Layer

Owner: `core/memory`

Responsibilities:

- resolve the active history source
- load canonical provider-native history
- provide structured normalized views
- preserve enough structure for higher-level adapters to make safe policy choices

Non-goals:

- deciding how every caller should flatten or summarize history

### 2. LLM-Facing Tool Adapter

Owner: `core/tools/memory_ops.py`

Responsibilities:

- expose broker data through the generic tool interface
- serialize results for model/tool consumption
- support inspection-oriented retrieval

Properties:

- permissive
- JSON/string-oriented
- not the authoritative safe path for context reconstruction

### 3. Monty-Facing History Helper

Owner: new authoring/helper layer over `core/memory`

Responsibilities:

- return structured Python objects directly to authored Python
- provide safer default semantics for context assembly
- make it difficult to manipulate tool-call / tool-return parts incorrectly

Expected behavior:

- preserved message order
- explicit logical tool-exchange handling
- flattening only via intentional helper operations
- clean text projection for summarization prompts without losing the original structured objects

### 4. Context Assembly

Owner: `assemble_context(...)`

Responsibilities:

- merge history, context messages, instructions, latest user message
- validate shape
- compose downstream prompt structure

Non-goals:

- discovering what valid message history is supposed to mean
- repairing lossy caller input

## Implementation Plan

### Phase 1: Add Monty History Helper

Status: complete

Add a new authoring capability/helper that calls `MemoryService` directly instead of routing through `call_tool("memory_ops", ...)`.

Requirements:

- returns structured Python objects, not JSON strings
- supports the same basic retrieval scope as current history access
- carries enough metadata for downstream safe use

Implemented name:

- `retrieve_history(...)`

### Phase 2: Introduce Safe History Units For Authoring

Status: complete

Define the structured objects the Monty helper returns.

At minimum, it should distinguish:

- plain conversational messages
- tool exchanges

Implemented shape:

- `HistoryMessage`
- `ToolExchange`

The important invariant is that authored Python should not receive lone tool-call or lone tool-return items by default when it is asking for history intended for context assembly.

### Phase 3: Update Default Context Template

Status: complete

Replace the current `call_tool("memory_ops", ...)` JSON path in `default.md` with the new structured helper.

Target outcome:

- no JSON round-trip for context history
- no default flattening to `{"role": ..., "content": ...}` at the template boundary
- any flattening or summarization becomes explicit

### Phase 4: Tighten `assemble_context(...)` Usage

Status: complete for the base path; follow-up validation still needed

Keep `assemble_context(...)` as a composition helper, but bias its intended inputs toward broker-derived structured history items rather than arbitrary flattened dicts.

Implemented:

- `assemble_context(...)` accepts `HistoryMessage` and `ToolExchange` directly
- `core/authoring/context_manager.py` restores those units back into provider-native `ModelMessage`s when compiling downstream history
- authored Python can read `item.text` or `history.text` to build clean summarization prompts without dumping raw provider payloads
- flattened dicts still work as an escape hatch, but they are no longer the default template path

## Invariants

- `core/memory` is the single source of truth for conversation-history retrieval semantics.
- Raw provider-native history remains available to internal runtime code.
- `memory_ops` may serialize and flatten because it is an LLM-facing tool adapter.
- Monty/context history access must default to safer semantics than `memory_ops`.
- Tool-call / tool-return fidelity must not be easy to break accidentally in the context path.
- Prompt-text rendering must be a projection of the structured object, not a replacement for the structured object.

## Validation Targets

Add or update targeted scenarios for:

1. Structured Monty history helper returns ordered conversation objects without JSON parsing.
2. Tool exchanges are exposed atomically to the context path.
3. Default context template no longer depends on `call_tool("memory_ops", ...)` for history.
4. Multimodal tool turns continue safely through multiple model requests.
5. Older history can still be intentionally flattened or summarized, but only by explicit transform steps.

## Open Design Questions

- Should the Monty helper expose both raw and safe/grouped modes, or only safe/grouped mode?
- Should grouped tool exchanges include the underlying raw provider messages for debugging/introspection?
- How much metadata should survive into `assemble_context(...)` by default?
- Should `memory_ops` remain fully permissive, or should it eventually gain an explicit “inspection vs safe context” mode?
