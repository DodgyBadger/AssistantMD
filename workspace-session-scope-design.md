# Workspace Session Scope Design

## Purpose

Add a lightweight chat-session workspace setting that lets a user associate a
chat session with a vault-relative folder. Context scripts can then load
workspace-local files such as `project_overview.md` without requiring a custom
context script per project folder.

This is intended as a convenience layer over existing vault files and context
scripts. It does not introduce a separate project model, change vault file
boundaries, or make workspace files authoritative by default.

## User Contract

- A chat session may have zero or one workspace.
- In the first implementation, a workspace is a vault-relative directory path.
- Empty workspace means no workspace-specific context is available.
- Workspace path resolution is always relative to the session's bound vault.
- Workspace does not change the vault root used by tools.
- Workspace does not restrict file access.
- Context scripts may choose to use the workspace path to load workspace-local
  context.
- Workspace is not exposed directly to the chat agent. Context scripts decide
  whether to include the workspace path, loaded files, or related instructions
  in assembled chat context.
- Existing sessions can edit workspace after an explicit unlock action.
- Workspace changes affect future context assembly only. Prior turns remain
  unchanged.

## Naming

Use `workspace` for the user-facing and script-facing concept.

Suggested persisted shape inside chat-session metadata:

```json
{
  "workspace": {
    "path": "Library/Stewardship/ProjectA"
  }
}
```

Suggested Monty global:

```python
workspace.path
workspace.exists
```

`workspace.path` should be an empty string when unset. `workspace.exists`
should be `False` when no workspace is set.

## UI Design

Add a `Session Workspace` control to the chat settings/session area:

- Text field accepts a vault-relative directory path.
- Folder icon button opens the existing sidebar modal pattern.
- The modal displays a folder-only vault directory picker.
- Selecting a folder writes its path into the text field.
- Clearing the text field removes the workspace path.
- After a session has started, the field is locked by default.
- An explicit `Unlock` action makes the field editable again.
- Save/validation feedback should happen before the next chat request where
  possible.

The picker should use lazy loading rather than rendering the whole vault tree at
once.

## API Shape

Add a directory listing endpoint shaped for the picker, for example:

```text
GET /api/vaults/{vault_name}/directories?path=Library/Stewardship
```

Example response:

```json
{
  "path": "Library/Stewardship",
  "directories": [
    {
      "name": "ProjectA",
      "path": "Library/Stewardship/ProjectA",
      "has_children": true
    }
  ]
}
```

Add a session workspace update endpoint for existing sessions, for example:

```text
PATCH /api/chat/sessions/{session_id}/workspace
```

Request:

```json
{
  "vault_name": "MyVault",
  "path": "Library/Stewardship/ProjectA"
}
```

For a new unsaved session, the chat execute request may include the workspace
path so the first turn can persist the session and workspace together.

## Session Summary Storage

Also save the normalized workspace path on the session summary record.

The chat-session metadata remains the source of truth for the active session's
workspace. Session summaries should denormalize the current workspace path so
summary retrieval can later filter by workspace without reparsing chat-session
metadata.

Prefer a dedicated nullable `workspace_path` column on `session_summaries` over
only storing it in `metadata_json`, because the expected future use is filtering:

```sql
workspace_path TEXT
```

Add an index suitable for vault-local workspace filtering:

```sql
CREATE INDEX IF NOT EXISTS idx_session_summaries_vault_workspace
ON session_summaries(vault_name, workspace_path);
```

The first implementation does not need to add workspace filtering to summary
search, but it should preserve the data needed for that future query shape.

## Validation Rules

Server-side validation is authoritative:

- Path must be empty or a string.
- Non-empty path must be relative.
- Reject `..`.
- Store a normalized slash-separated vault-relative path.
- Do not require saved workspace paths to currently exist. A vault
  reorganization may leave old sessions with stale workspace paths, and that is
  acceptable.

Directory-picker browsing is stricter because it reads the current vault tree:

- Resolve symlinks and ensure the browsed path stays inside the vault.
- Require the browsed path to exist.
- Require the browsed path to be a directory.

Dot-prefixed folders and the vault-local `AssistantMD` runtime directory should
be excluded from the workspace picker by the API, not only the UI.

## Context Script Contract

Expose workspace as a read-only reserved Monty input for context scripts.
The chat agent only sees workspace information if the selected context script
includes it in assembled history or instructions.

Default context script can optionally load:

```python
if workspace.exists:
    overview = await file_ops_safe(
        operation="read",
        path=f"{workspace.path}/project_overview.md",
    )
```

The default context script should treat a missing overview as normal and
continue without error.

Do not make the filename configurable in the first pass unless a concrete need
appears. Custom context scripts can use the same `workspace` global for other
conventions.

## Workflow Relationship

Workflows are currently vault-scoped. They run as `vault/name`, use the vault
root for file operations, and are serialized by vault-level workflow lanes.

Workspace should not change scheduled workflow semantics in the first
implementation.

Future extensions may pass workspace explicitly into chat-triggered workflows or
allow workflows to declare that workspace is optional or required. That should
be an explicit workflow contract, not an implicit change to all workflows.

## Affected Areas

- `core/chat/chat_store.py`: persist and update workspace metadata.
- `core/memory/schema.py` and `core/memory/session_summary.py`: persist
  `workspace_path` on session summaries for future workspace-filtered
  retrieval.
- `api/models.py`: request/response models for workspace and directory listing.
- `api/services.py`: workspace validation, update service, directory listing.
- `api/endpoints.py`: workspace update and directory listing endpoints; chat
  execute payload parsing for first-turn workspace.
- `core/authoring/runtime/host.py`: reserved Monty input and dataclass for
  workspace.
- `core/authoring/context_manager.py`: pass workspace into the chat context
  host.
- `core/authoring/seed_templates/context/default.md`: optional
  `project_overview.md` loading.
- `static/index.html` and `static/app.js`: text field, folder button, unlock
  behavior, sidebar modal folder picker, request payload wiring.
## Validation Target

Add or extend an integration scenario that verifies:

- A chat request can persist a workspace path on first turn.
- A generated or updated session summary stores the normalized workspace path.
- Session list/detail responses include the workspace.
- Invalid workspace paths are rejected with a stable API error.
- A context template can read `workspace.path` and load
  `workspace/project_overview.md`.
- Missing `project_overview.md` does not fail context assembly.
- Updating workspace after unlock affects a later turn's context assembly.

Maintainers own the full validation suite. Agents should run focused local
checks only and request full validation results.

## Deferred Questions

- Should session summaries display workspace in the preview surface?
- Should summary search add workspace filtering once there is a UI affordance
  for it?
