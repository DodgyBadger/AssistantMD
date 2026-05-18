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
  `search`, `deep`, and `related`. Defaults to `search`.
- `query`: search phrase for the default `search` mode and for `deep` mode.
- `limit`: optional positive integer result limit for `search_sessions`.
- `data`: optional object for `upsert_session_memory`. Supported keys are
  `summary`, `domain`, `work_product`, `user_intent`, `named_entities`,
  `source_summary`, `artifacts`, and `metadata`.
- `extraction_model`: optional model alias for `extract_session_memory`.

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
- `source_summary`: concise bullet summary of source material or prior context
  the session appears to have drawn on, based on tool calls/results and the
  session summary. Include vault files, web pages, retrieved memories, imported
  docs, or user-pasted source text when identifiable. Do not judge source
  quality.

For manual writes, put these fields inside `data`. `data.artifacts` is an
optional list of artifact objects with `path`, optional `artifact_role`, and
`metadata`. `data.metadata` is optional JSON object metadata for the memory row.

## Output Shape

Returns pretty-printed JSON text. Successful operations include a stable
`status` and `operation` value, plus operation-specific data such as
`session_memory` or ranked `matches`.

## Notes

- `get_session_memory` is read-only. It fetches the memory row for the current
  or specified session and returns `status: "found"` or `status: "not_found"`.
- `extract_session_memory` reads the transcript and structured tool events for
  the current or specified session, runs AssistantMD's standard extraction
  policy, upserts the resulting memory fields, attaches any vault files mutated
  by that chat session as artifacts, and indexes vector-searchable fields.
- `upsert_session_memory` manually stores the `data` values supplied by the
  caller for the current or specified session. It does not read the transcript
  or infer missing fields.
- `search_sessions` finds candidate prior sessions.
  - `mode: "search"` is the default. It searches the supplied `query` across memory fields using
    lexical FTS/BM25 evidence plus semantic vector evidence.
  - `mode: "deep"` searches memory fields plus raw chat transcripts.
  - `mode: "related"` compares an already-extracted current or specified session
    against prior sessions using stored memory fields.
- Use `search` for normal live-chat lookup when the current session does not
  yet have stored memory, or when the user names a specific word, phrase, topic,
  or concept.
- Use `deep` when the user asks for a broader or transcript-level search.
- Use `related` only when investigating an existing session that already has
  stored memory and you want to find neighboring sessions.
- For `search` and `deep`, include `query` as a plain natural-language phrase.
  Do not use explicit boolean syntax such as uppercase `AND`/`OR`. Use a
  positive integer `limit`.

## Common Calls

Fetch memory for the current session:

```json
{"operation": "get_session_memory"}
```

Extract memory for the current session:

```json
{"operation": "extract_session_memory"}
```

Manually store memory fields for the current session:

```json
{
  "operation": "upsert_session_memory",
  "data": {
    "summary": "Drafted a donor update about wetland restoration.",
    "domain": "conservation fundraising",
    "work_product": "donor update",
    "user_intent": "Prepare a donor-facing update about restoration progress.",
    "named_entities": "North Star Foundation",
    "source_summary": "Drew on wetland restoration progress notes and prior donor reporting context.",
    "artifacts": [
      {"path": "Reports/Wetlands/donor-update.md", "artifact_role": "output"}
    ],
    "metadata": {"source": "manual"}
  }
}
```

Search memory fields for a user-named concept:

```json
{"operation": "search_sessions", "query": "greenhouse gas accounting", "limit": 5}
```

Search memory fields and raw transcripts:

```json
{"operation": "search_sessions", "mode": "deep", "query": "greenhouse gas accounting", "limit": 5}
```

Find sessions related to an already-extracted session:

```json
{"operation": "search_sessions", "mode": "related", "session_id": "existing-session-id", "limit": 5}
```
