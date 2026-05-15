# `memory_ops`

## Purpose

Manage memory extracted from chat sessions.

This tool is available to chat and context scripts as the direct operation
surface for session memory lookup, field search, and session-memory updates.

## Parameters

- `operation`: required. Supported values are `extract_session_memory`,
  `upsert_session_memory`, `get_session_memory`, `search_sessions`, and
  `find_related_sessions`.
- `session_id`: optional explicit session id. Defaults to the active session
  when available.
- `limit`: optional positive integer or `all`.
- `title`: optional human-readable session label.
- `summary`: optional short plain-language summary of the chat session.
- `domain`: optional subject area or knowledge area.
- `work_product`: optional concrete thing the user wanted produced or answered.
- `user_intent`: optional user goal or intent after clarification or topic
  drift.
- `named_entities`: optional named people, organizations, and places.
- `field_type` and `value`: optional field pair for `search_sessions`.
- `extraction_model`: optional model alias for `extract_session_memory`.
- `artifacts`: optional list of artifact objects with `path`, optional
  `artifact_role`, and `metadata`.
- `metadata`: optional JSON object for `upsert_session_memory`.

## Session Memory Field Contract

Use these fields as short summaries of one chat session. Prefer durable
descriptions of the user's work over momentary prompt phrasing.

- `summary`: short plain-language summary of the whole chat session. Include
  enough context for a human to quickly understand what happened.
- `domain`: the subject area or knowledge area of the work, such as
  `data visualization`, `nutrition`, `ServiceNow administration`, `statistics`,
  `research synthesis`, or `conservation fundraising`.
- `work_product`: the concrete thing the user wanted produced or answered, such
  as `Python script`, `recipe`, `article summary`, `stacked bar chart`,
  `rewrite`, `donor email`, or `factual answer`.
- `user_intent`: the user's underlying goal or intent after clarification,
  repetition, or topic drift. Write this as what the user wants to accomplish,
  not what the assistant should do next.
- `named_entities`: only named people, organizations, and places. Use a concise
  comma- or semicolon-separated text list. Leave empty if there are no named
  people, organizations, or places.

Update only fields that are known from the current context. Leave unknown fields
empty.

## Output Shape

Returns pretty-printed JSON text. Successful operations include a stable
`status` and `operation` value, plus operation-specific data such as
`session_memory`, `session_memories`, or field-aware `matches`.

## Notes

- The selected runtime vault is always the search/write scope. `memory_ops` does
  not accept a vault selector parameter.
- `get_session_memory` is read-only. It fetches the memory row for the current
  or specified session and returns `status: "found"` or `status: "not_found"`.
- `extract_session_memory` reads the persisted transcript for the current or
  specified session, runs AssistantMD's standard two-step extraction policy,
  upserts the resulting memory fields, and indexes vector-searchable fields.
- `upsert_session_memory` creates memory for the current or specified session,
  or updates the supplied fields when memory already exists. It does not create
  a separate project or work object.
- `search_sessions` is the retrieval primitive for finding candidate prior
  sessions. The current implementation searches indexed session memory fields.
  When `field_type` and `value` are supplied, it searches within that field
  type. Semantic vector matches are available for `summary`, `domain`,
  `work_product`, and `user_intent`; `named_entities` uses case-insensitive
  wildcard matching. Future implementations may also search full transcripts or
  linked vault artifacts behind this same operation.
- `find_related_sessions` is the higher-level retrieval policy for finding
  prior sessions related to the current or specified session. It uses the stored
  memory fields for that session, compares `domain`, `work_product`, and
  `user_intent`, returns ranked matches with `automatic_recommendation` or
  `possible_related` bands, and includes per-field score contributions. It
  accepts only `session_id` and `limit`; use `search_sessions` for caller-driven
  field queries.
- `upsert_session_memory` indexes vector-searchable direct fields immediately
  after updates. If embedding is unavailable, the write still succeeds and
  non-vector search remains available.
- Conversation history is intentionally not exposed through this tool. If chat
  history needs to become memory, extract it into session memory fields or
  export it as vault material first.
