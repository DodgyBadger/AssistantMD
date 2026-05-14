# `memory_ops`

## Purpose

Manage workstream memory.

This tool is available to chat and context scripts as the direct operation
surface for current workstreams, workstream search, artifacts, session links,
and direct workstream field updates.

## Parameters

- `operation`: required. Supported values are `create_workstream`,
  `get_workstream`, `search_workstreams`, `link_session`, and
  `update_workstream`.
- `session_id`: optional explicit session id.
- `vault_name`: optional explicit vault name. Defaults to the active vault when
  available.
- `limit`: optional positive integer or `all`.
- `workstream_id`: workstream id for explicit workstream reads, links, and
  updates. Omit it with `get_workstream` to read the workstream linked to the
  current session.
- `title`: optional title for `create_workstream` or `update_workstream`.
- `status`: optional workstream status for `create_workstream` or
  `update_workstream`.
- `type`: optional task/deliverable type text.
- `topic`: optional topic/theme text. This can be a phrase or sentence, not just
  a single label.
- `entities`: optional people, organizations, and other named entities text.
- `project`: optional project/program text.
- `objective`: optional objective text.
- `strategy`: optional strategy, reusable approach, or preference text.
- `field_type` and `value`: optional field pair for `search_workstreams`.
- `artifacts`: optional list of artifact objects with `path`, optional
  `artifact_role`, `vault_name`, and `metadata`.
- `metadata`: optional JSON object for `create_workstream`.

## Workstream Field Contract

Use these fields as short summaries of the user's unit of work. Prefer durable,
work-level descriptions over momentary chat phrasing.

- `title`: human-readable label for the workstream. Use a compact noun phrase
  that would make sense in a list, such as `Wetlands donor report`.
- `type`: the kind of work being done or deliverable being produced. Use a
  stable category-like phrase, such as `donor report`, `grant proposal`,
  `weekly planning`, `performance review`, `retrieval`, or `snippet synthesis`.
  Do not put the subject matter here.
- `topic`: the subject/theme of the work. This can be a sentence when a short
  label would lose meaning, such as `Riparian restoration funding narrative for
  watershed protection`. Do not list people or organizations here unless they
  are part of the subject itself.
- `entities`: named people, organizations, funders, clients, partners, places,
  or other proper-noun entities relevant to the work. Use a concise comma- or
  semicolon-separated text list. Do not use this for broad themes.
- `project`: the user's project, program, client engagement, initiative, or
  internal work area that scopes the work. Leave empty if there is no clear
  project/program scope.
- `objective`: what the user is trying to accomplish in this workstream. Write a
  short outcome-oriented phrase or sentence, not a transcript of the latest
  request.
- `strategy`: reusable approach, format, style preference, decision, constraint,
  or tactic that may help similar future work. Use this for cross-workstream
  carryover such as `reuse the three-section donor report format`.

Update only fields that are known from the current context. Do not invent
specific entities, projects, or objectives to fill blanks.

## Output Shape

Returns pretty-printed JSON text. Successful workstream operations include a
stable `status` and `operation` value, plus operation-specific data such as a
`workstream`, `workstreams`, or field-aware `matches` list.

## Notes

- `get_workstream` is read-only. With `workstream_id`, it fetches that
  workstream and returns `status: "found"` or `status: "not_found"`. Without
  `workstream_id`, it fetches the workstream linked to the current session and
  returns `status: "linked"` or `status: "unlinked"`. Returned workstreams
  include direct workstream fields and artifacts.
- `link_session` links the current or specified session to a workstream. If the
  session is already linked, the existing link is replaced.
- Session links are scoped to the selected vault. Linking a session to an
  unrelated vault's workstream is rejected.
- `update_workstream` replaces any supplied direct field value. For example,
  `topic="Riparian restoration grant for watershed protection"` replaces the
  previous topic text instead of appending another topic row.
- `search_workstreams` is the retrieval primitive for finding candidate
  workstreams by known fields. When `field_type` and `value` are supplied, it
  searches within that field type. Semantic vector matches are available for
  `type`, `topic`, `objective`, and `strategy`; `entities` and `project` use
  case-insensitive wildcard matching.
- `create_workstream` and `update_workstream` index vector-searchable direct
  fields immediately after updates. If embedding is unavailable, the write still
  succeeds and non-vector search remains available.
- Conversation history is intentionally not exposed through this tool. If chat
  history needs to become memory, it should first be exported or extracted into
  vault artifacts or direct workstream fields.
