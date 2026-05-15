# `memory_ops`

## Purpose

Manage memory extracted from chat sessions.

This tool is available to chat and context scripts as the direct operation
surface for session memory lookup, search, and session-memory updates.

The selected runtime vault is always the scope. Do not pass or infer a vault
parameter.

## Parameters

- `operation`: required. Supported values are `extract_session_memory`,
  `upsert_session_memory`, `get_session_memory`, and `search_sessions`.
- `session_id`: optional explicit session id. Defaults to the active session
  when available.
- `mode`: optional search mode for `search_sessions`. Supported values are
  `related`, `search`, and `deep`. Defaults to `related`.
- `query`: optional search phrase for `search` and `deep` modes.
- `limit`: optional positive integer result limit for `search_sessions`.
- `title`: optional human-readable session label.
- `summary`: optional short plain-language summary of the chat session.
- `domain`: optional subject area or knowledge area.
- `work_product`: optional concrete thing the user wanted produced or answered.
- `user_intent`: optional user goal or intent after clarification or topic
  drift.
- `named_entities`: optional named people, organizations, and places.
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
`session_memory` or ranked `matches`.

## Notes

- `get_session_memory` is read-only. It fetches the memory row for the current
  or specified session and returns `status: "found"` or `status: "not_found"`.
- `extract_session_memory` reads the persisted transcript for the current or
  specified session, runs AssistantMD's standard two-step extraction policy,
  upserts the resulting memory fields, and indexes vector-searchable fields.
- `upsert_session_memory` creates memory for the current or specified session,
  or updates the supplied fields when memory already exists. It does not create
  a separate project or work object.
- `search_sessions` is the retrieval primitive for finding candidate prior
  sessions.
  - `mode: "related"` is the default. It compares the current or specified
    session against prior sessions using stored memory fields.
  - `mode: "search"` searches the supplied `query` across memory fields using
    lexical FTS/BM25 evidence plus semantic vector evidence.
  - `mode: "deep"` searches memory fields plus raw chat transcripts. Transcript
    matches use lexical FTS/BM25 evidence.
- Use `related` for general related-session lookup.
- Use `search` when the user names a specific word, phrase, topic, or concept.
- Use `deep` when the user asks for a broader or transcript-level search.
- For `search` and `deep`, write `query` as a plain natural-language phrase.
  Do not use explicit boolean syntax such as uppercase `AND`/`OR`. Use a
  positive integer `limit`.
- `upsert_session_memory` indexes vector-searchable direct fields immediately
  after updates. If embedding is unavailable, the write still succeeds and
  non-vector search remains available.
- Conversation history is intentionally not exposed through this tool. If chat
  history needs to become memory, extract it into session memory fields or
  export it as vault material first.

## Common Calls

Fetch memory for the current session:

```json
{"operation": "get_session_memory"}
```

Extract memory for the current session:

```json
{"operation": "extract_session_memory"}
```

Find sessions related to the current session:

```json
{"operation": "search_sessions"}
```

Search memory fields for a user-named concept:

```json
{"operation": "search_sessions", "mode": "search", "query": "greenhouse gas accounting", "limit": 5}
```

Search memory fields and raw transcripts:

```json
{"operation": "search_sessions", "mode": "deep", "query": "greenhouse gas accounting", "limit": 5}
```
