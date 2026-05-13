# `memory_ops`

## Purpose

Manage work episode memory.

This tool is available to chat and context scripts as the direct operation
surface for current work episodes, related work, episode fields, artifacts,
session links, and feedback. Chat agents can use it when the tool is selected
for the current run.

## Parameters

- `operation`: required. Supported values are `current_episode`,
  `create_episode`, `get_episode`, `search_episodes`, `related_episodes`,
  `episode_artifacts`, `link_session`, `relink_session`, `unlink_session`,
  `update_episode`, and `record_feedback`.
- `session_id`: optional explicit session id.
- `vault_name`: optional explicit vault name. Defaults to the active vault when
  available.
- `limit`: optional positive integer or `all`.
- `episode_id`: episode id for episode reads, links, updates, artifact reads,
  and feedback.
- `related_episode_id`: related episode id for `record_feedback`.
- `title`: optional title for `create_episode`.
- `status`: optional episode status for `create_episode`.
- `field_type` and `value`: optional single field pair for `search_episodes` or
  `update_episode`.
- `fields`: optional list of field objects with `field_type`, `value`, optional
  `normalized_value`, `confidence`, and `source`.
- `artifacts`: optional list of artifact objects with `path`, optional
  `artifact_role`, `source`, `vault_name`, and `metadata`.
- `metadata`: optional JSON object for `create_episode`.
- `link_source`: source label for `link_session` and `relink_session`.
- `confidence`: confidence for created episodes, links, and added fields.
- `action` and `reason`: feedback values for `record_feedback`.

## Output Shape

Returns pretty-printed JSON text. Successful work episode operations include a
stable `status` and `operation` value, plus operation-specific data such as an
`episode`, `episodes`, `candidates`, or `artifacts` list.

## Notes

- `current_episode` is read-only. It returns `status: "unlinked"` when the
  current session is not attached to a work episode.
- Session links are scoped to the selected vault. Linking a session to an
  episode from another vault is rejected.
- `related_episodes` currently returns exact, field-aware candidates. Semantic
  field-vector retrieval is implemented in the memory store and will be wired
  into higher-level retrieval policy in a later slice.
- Conversation history is intentionally not exposed through this tool. If chat
  history needs to become memory, it should first be exported or extracted into
  vault artifacts or work episode fields.
