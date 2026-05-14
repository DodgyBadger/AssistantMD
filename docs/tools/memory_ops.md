# `memory_ops`

## Purpose

Manage workstream memory.

This tool is available to chat and context scripts as the direct operation
surface for current workstreams, related work, workstream fields, artifacts,
session links, and feedback. Chat agents can use it when the tool is selected
for the current run.

## Parameters

- `operation`: required. Supported values are `current_workstream`,
  `create_workstream`, `get_workstream`, `search_workstreams`, `related_workstreams`,
  `workstream_artifacts`, `link_session`, `relink_session`, `unlink_session`,
  `update_workstream`, and `record_feedback`.
- `session_id`: optional explicit session id.
- `vault_name`: optional explicit vault name. Defaults to the active vault when
  available.
- `limit`: optional positive integer or `all`.
- `workstream_id`: workstream id for workstream reads, links, updates, artifact reads,
  and feedback.
- `related_workstream_id`: related workstream id for `record_feedback`.
- `title`: optional title for `create_workstream`.
- `status`: optional workstream status for `create_workstream`.
- `field_type` and `value`: optional single field pair for `search_workstreams` or
  `update_workstream`.
- `fields`: optional list of field objects with `field_type`, `value`, optional
  `normalized_value`, `confidence`, and `source`.
- `artifacts`: optional list of artifact objects with `path`, optional
  `artifact_role`, `source`, `vault_name`, and `metadata`.
- `metadata`: optional JSON object for `create_workstream`.
- `link_source`: source label for `link_session` and `relink_session`.
- `confidence`: confidence for created workstreams, links, and added fields.
- `action` and `reason`: feedback values for `record_feedback`.

## Output Shape

Returns pretty-printed JSON text. Successful workstream operations include a
stable `status` and `operation` value, plus operation-specific data such as a
`workstream`, `workstreams`, `candidates`, or `artifacts` list.

## Notes

- `current_workstream` is read-only. It returns `status: "unlinked"` when the
  current session is not attached to a workstream.
- Session links are scoped to the selected vault. Linking a session to an
  unrelated vault's workstream is rejected.
- `related_workstreams` currently returns exact, field-aware candidates. Semantic
  field-vector retrieval is implemented in the memory store and will be wired
  into higher-level retrieval policy in a later slice.
- Conversation history is intentionally not exposed through this tool. If chat
  history needs to become memory, it should first be exported or extracted into
  vault artifacts or workstream fields.
