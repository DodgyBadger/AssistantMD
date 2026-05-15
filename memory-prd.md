# PRD: Session Memory and Adaptive Context

## Summary

AssistantMD memory helps the agent find relevant prior chat sessions inside the
current vault. Each chat session can have one memory record: a compact summary,
the user's intent, classification fields for retrieval, named entities, and
optional artifact references.

The vault remains the source of truth. Session memory does not replace vault
files with a hidden project database. It gives the context manager and chat
agent a transparent index of prior work so they can suggest, retrieve, or reuse
relevant context.

## Goals

- Give users useful continuity across chat sessions without requiring custom
  context scripts for every project.
- Store memory at the chat-session boundary so the transcript remains the clear
  provenance unit.
- Retrieve related prior sessions by field-aware matching.
- Keep memory transparent by exposing why a session matched.
- Preserve composability by exposing the same memory primitive to chat agents
  and authored context scripts through `memory_ops`.
- Avoid hidden cross-session merge logic until real usage proves that a higher
  level aggregation is needed.

## Non-Goals

- No hidden always-on summarization of the entire vault.
- No separate project/work aggregation object in v1.
- No manual session-to-project linking or relinking.
- No semantic search over the whole vault.
- No automatic promotion of generated summaries into authoritative vault notes.
- No replacement for context assembly scripts.

## Core Concepts

### Vault

The selected vault is a hard scope. Session memory lookup should not cross vaults
unless a future feature explicitly adds cross-vault retrieval.

### Session Memory

Session memory is one extracted record for one chat session. It is keyed by
`vault_name` and `session_id`, so deleting a chat session can delete the memory
for that same session.

Recommended fields:

```yaml
session_id:
vault_name:
title:
created_at:
updated_at:

summary:
domain:
work_product:
user_intent:
named_entities:

artifacts:
  - path:
    artifact_role:
    metadata:

metadata:
```

Field policy:

- `summary`: durable plain-language summary of what happened in the session.
- `user_intent`: what the user was trying to accomplish after clarification,
  repetition, or topic drift.
- `domain`: subject area or knowledge area.
- `work_product`: concrete thing the user wanted produced or answered.
- `named_entities`: named people, organizations, and places.

`summary` and `user_intent` are the most durable extracted fields. `domain`,
`work_product`, and `named_entities` are derived retrieval fields and can be
rebuilt from the durable fields if the extraction policy changes.

### Adaptive Context Assembly

Memory feeds context assembly. A default memory-aware context policy can inspect
the current session, search prior session memories, and present likely related
sessions as optional context. User-authored context scripts can call the same
`memory_ops` tool or ignore memory entirely.

## Product Behavior

### During Chat

The agent or context policy may call:

```python
await memory_ops(operation="upsert_session_memory", ...)
await memory_ops(operation="extract_session_memory")
await memory_ops(operation="get_session_memory")
await memory_ops(operation="search_sessions", field_type="domain", value="wetlands")
await memory_ops(operation="find_related_sessions", limit=5)
```

No separate linking step is required. The active session is the memory identity.
`find_related_sessions` only takes a session and limit; caller-supplied field
queries belong to `search_sessions`.

### Future Chat Retrieval

When a future chat resembles prior work, AssistantMD should retrieve related
sessions by field-aware matching:

- same or related domain
- similar work product
- similar user intent
- overlapping named entities

The first recommended compound policy is:

```text
score = 0.45 * domain
      + 0.35 * work_product
      + 0.20 * user_intent
```

Suggested bands:

- `>= 0.70`: automatic recommendation
- `0.55-0.70`: possible related work
- `< 0.55`: hide

`summary` should be used for display and explanation, not first-pass ranking.

## User Control

The user should be able to:

- use a context script that never writes or retrieves memory
- ask the agent to update the current session memory
- ask the agent to search prior session memory
- continue an old chat session directly when they want true continuity
- use retrieved prior sessions as context candidates without merging them into
  the current session

## Implementation Notes

- Store session memory in `system/memory.db`.
- Keep direct text fields on the `session_memories` row.
- Store vectors for `summary`, `domain`, `work_product`, and `user_intent`.
- Use wildcard text search for `named_entities`.
- `upsert_session_memory` creates a session memory row or updates supplied
  fields on an existing row.
- `extract_session_memory` runs the standard transcript extraction policy, then
  writes through `upsert_session_memory`.
- Index vectors on create/update. If embedding is unavailable, the write should
  still succeed and non-vector search remains available.
- Delete session memory when a chat session is deleted or purged.

## Validation Expectations

- Session memory extract/create/update/get/search works through `memory_ops`.
- Related-session retrieval works through `memory_ops` and exposes per-field
  contribution evidence.
- Chat agents can call `memory_ops` through the normal tool path.
- Field-aware semantic search retrieves related sessions without crossing vaults.
- Live extraction probes produce consistent `summary`, `user_intent`, `domain`,
  `work_product`, and `named_entities`.
- Compound retrieval probes remain inspectable as artifacts.
