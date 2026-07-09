# Inline Editor Implementation Plan

## Goal

Make vault file interaction part of the chat workflow without recreating a full
markdown editor or vault explorer. The chat remains the primary surface; file
selection, inspection, and edit approval appear only when they help a concrete
conversation.

## Product Direction

AssistantMD already lets the agent find files through `file_ops`, especially
inside a chat workspace. Explicit file references are not required for basic
agent capability. They are useful when the user wants to make intent exact:

- disambiguate similarly named files;
- reference files outside the current workspace without switching to Obsidian to
  copy vault-relative paths;
- constrain a turn to known files or folders;
- open files mentioned by the agent without another app hop;
- review and approve proposed edits with human control.

The design should keep these as optional fast paths. Natural language chat and
agent-side discovery remain the default workflow.

## Non-Goals

- No persistent full-vault tree sidebar.
- No Obsidian-style workspace, backlinks, graph, panes, or tabbed editor.
- No requirement that users explicitly reference files for normal chat tasks.
- No hidden database ownership of user content; vault files remain canonical.
- No direct file writes that bypass vault-state mutation recording.

## Phase 1: Chat-Native File References

Deliver the smallest useful workflow: select or type vault-relative file
references from the chat composer, and open referenced files from chat.

### Architecture

Phase 1 should not require the assistant to emit custom UI syntax. File
references come from two deterministic sources:

- composer reference state created by the user through the picker or `@path`
  autocomplete;
- post-processed assistant markdown where the UI recognizes existing
  vault-relative paths and upgrades them into openable links.

The model still sees ordinary text such as `Clients/Acme/Brief.md`. The UI may
display that reference as a chip or link, but the transcript remains legible
without the UI layer.

Chat instructions should teach one stable convention: user-facing vault file
references use `@vault-relative/path.md` text, not custom HTML. Plain text is
preferred, but the UI should tolerate inline-code refs because models commonly
format paths that way. Paths should be vault-root relative, use forward slashes,
and include the extension when known.

### User Experience

- Add a composer control for file references.
- Open a lightweight reference picker rooted at the active chat workspace when
  one is set.
- Support searching the whole vault so files outside the workspace are easy to
  reference.
- Bias results toward the workspace, recent files, and likely markdown files,
  but do not hide vault-wide matches.
- Insert selected files as visible references in the prompt, either as chips
  backed by structured state or as a clear textual representation.
- Add an autocomplete path for keyboard users, likely `@path`, backed by the same
  reference model as the picker.
- Render assistant-mentioned vault file paths as links when they can be safely
  recognized.
- Clicking a file reference opens a contextual file modal/panel for read and
  edit.

### File Modal Contract

- Resolve only vault-relative paths under the selected vault.
- Default to read/preview mode.
- Offer edit mode for supported text/markdown files.
- Save with optimistic concurrency using a content hash from open time.
- Route saves through `core.vault_state.file_mutations.replace_vault_file_content`
  or the appropriate shared mutation helper.
- Refresh vault state after successful writes through the existing mutation path.
- Show a clear conflict error if the file changed externally before save.

### Backend Surface

Add API/service/model contracts for generic vault file operations:

- read a vault file by `vault_name` and vault-relative `path`;
- write supported text files with `content` and `expected_sha256`;
- optionally list/search workspace or vault files for the picker.

The API layer should remain thin. Path normalization, vault lookup, content
limits, text/binary support, hash generation, and mutation routing belong in
service/core helpers.

### Frontend Surface

- Add a small module for the reference picker and file modal rather than growing
  `static/app.js` substantially.
- Maintain one client-side reference model shared by picker selection,
  autocomplete insertion, chips, and prompt serialization.
- Reuse modal/button conventions from workflow file editing.
- Keep composer references compact and removable.
- Ensure mobile users can use the modal picker without relying on slash or
  mention syntax.
- Ensure desktop keyboard users can insert references without leaving the input.
- After assistant markdown is sanitized and rendered, run a vault-link
  post-processor that upgrades recognized file-path text or markdown links into
  buttons/anchors that call the file modal. Do not ask the model to emit custom
  attributes or HTML for this.

## Phase 2: Collaborative Edit Proposals

Build on Phase 1 by making proposed edits interactive chat artifacts.

### Architecture

Do not introduce a custom assistant-authored DSL for review controls, buttons, or
editable blocks. The assistant should not be responsible for rendering
interactive HTML. Instead, introduce server-owned UI artifacts:

1. The model uses a normal tool call with a JSON schema, such as
   `propose_file_edits`.
2. The tool validates the proposal, resolves vault paths, captures current file
   hashes/snippets, and stores an edit-proposal artifact.
3. The chat stream or persisted tool event exposes an `artifact_ref` and compact
   metadata.
4. The UI artifact renderer fetches the artifact and renders per-row review
   decisions, editable blocks, diffs, comments, and submit/apply controls.
5. Applying edits calls an API endpoint that validates selected operations and
   current file hashes before writing through vault-state mutation helpers.
6. Agent-facing review instructions live in `core/constants.py`. The UI sends
   structured review decisions to a backend review endpoint; the backend applies
   approved rows, builds the follow-up prompt, and starts the chat task while
   preserving a separate user-visible display prompt for chat history.

This keeps the LLM interface on well-supported ground: function/tool calling and
JSON Schema. The browser owns rendering, and the server owns validation.

### User Experience

- The assistant can present a proposal card containing one or more file edits.
- Each edit has:
  - an explicit review decision: approve, comment, deny, or pending;
  - a vault file link;
  - a short purpose/rationale;
  - a before/after snippet or compact diff;
  - optional live-editable replacement text where practical.
- The user submits review choices with one action. Approved rows are written
  through the proposal apply endpoint, including mixed reviews.
- Commented or denied rows are sent as a normal chat review prompt asking the
  assistant to revise only the unresolved proposal items.
- Denied rows mean "reject this change"; the generated review prompt should
  instruct the assistant not to apply or re-propose them unless the user asks
  for an alternative.
- Review instruction snippets are backend-owned constants, not frontend string
  literals.
- Submitted proposal cards become historical context: they lock review controls
  and collapse to the header after a successful apply or review submission.
- Applied edits should produce normal vault mutation activity and openable file
  references in the chat result.

### Contract Options To Evaluate

1. Preferred: a dedicated tool/API artifact for edit proposals, referenced from
   the chat through `artifact_ref`.
2. Possible fallback: a backend draft object persisted only long enough for
   approval.
3. Avoid for writes: structured assistant markdown that the UI parses into
   authorized write operations.

Prefer the simplest contract that is durable enough for reloads and does not
depend on fragile markdown parsing for write authorization.

### Artifact Storage

The proposal artifact must survive page reloads and persisted chat reloads at
least as long as the chat session does. Implementation options:

- add a small chat artifact table keyed by `artifact_ref`, session id, vault
  name, type, JSON payload, created time, and status;
- or extend existing tool-event artifact handling if it already provides enough
  durable payload lookup for UI rendering.

The artifact payload should be application data, not pre-rendered HTML.

Initial artifact types:

- `file_reference`: optional future normalized representation for user-selected
  file/folder references;
- `action_prompt`: a trusted UI action with label, description, optional icon,
  and a predefined chat prompt/action payload;
- `edit_proposal`: one or more proposed text edits with path, base hash, preview
  snippets, replacement text or patch, and selected/default state.

### Edit Proposal Safety Requirements

- The UI must not apply arbitrary assistant text as writes without a structured,
  server-validated operation.
- Each proposed write must carry vault name, vault-relative path, base hash, and
  intended replacement content or patch.
- Applying selected edits must validate current file hashes and report conflicts.
- Writes must route through vault-state mutation helpers for audit, snapshots,
  and rollback compatibility.
- Applied artifact status should be updated so reloads do not show stale
  proposals as unapplied.
- Inline user edits to a proposal update the pending artifact/application
  request, not the original assistant message text.

## Phase 3: Context-Script UI Actions

Once the artifact renderer exists, allow trusted context assembly scripts to add
small interactive action prompts to the chat start surface without involving the
LLM.

### Scenario

When a user starts a chat with a workspace set, a context script can inspect the
workspace. If `README.md` is missing, it can emit an `action_prompt` artifact:

- label: `Initialize workspace`;
- description: create a useful `README.md` for this workspace;
- prompt payload: ask the agent to review the workspace and create the README.

The UI renders this as a button near the chat start panel or first assistant
context area. Pressing it fills or sends the stock prompt through the normal chat
path. The model receives an ordinary user prompt; it does not render or
authorize the button.

### Architecture

Context scripts currently return `AssembleContextResult` with `messages` and
`instructions`. Extend the context assembly contract to optionally return UI
artifacts/actions, for example:

- `ui_artifacts: tuple[ContextUiArtifact, ...]` on `AssembleContextResult`; or
- a dedicated host helper such as `add_ui_action(...)` whose captured artifacts
  are returned alongside assembled context.

Prefer the narrowest API that keeps UI actions out of prompt text while allowing
Monty scripts to create trusted, typed artifacts. Scripts should describe
domain actions, not raw buttons:

- good: `suggest_chat_action(label=..., prompt=..., scope=...)`;
- avoid: `create_ui_element(type="button", css=..., onclick=...)`.

### Safety Requirements

- Context-script UI actions must be typed, server-validated data, not HTML.
- Action prompts may fill the composer by default; auto-send should be explicit
  per artifact type and easy to disable.
- Actions should be scoped to the active vault/session/workspace and should not
  persist as durable user content unless explicitly saved.
- The artifact should record its source as `context_script` with template id and
  workspace metadata for debugging.
- Prompt payloads should remain readable in the chat transcript after use.

## Relevant Existing Contracts

- `docs/architecture/api-ui.md`: API endpoints should stay thin and service-led.
- `docs/adr/0005-vault-mutation-audit-and-snapshots.md`: vault writes must route
  through shared mutation infrastructure.
- `docs/adr/0016-vault-files-canonical-user-data.md`: vault files are canonical
  user data.
- `static/js/workflow-actions.js`: existing modal text editor pattern for
  workflow files.
- `static/js/chat-rendering.js`: assistant markdown rendering and link
  post-processing surface.
- `static/js/workspace-picker.js`: existing workspace-oriented modal behavior.

## Reuse And Refactor Targets

Use these existing pieces before adding new parallel implementations:

- `core.vault_state.pathing.normalize_vault_relative_path` and
  `resolve_vault_relative_path` for vault-relative path normalization and
  boundary checks. If read/list APIs need behavior that currently lives only in
  `file_ops_safe`, extract shared helpers instead of copying validation logic.
- `core.vault_state.file_mutations.replace_vault_file_content` for UI file
  saves so mutation audit, snapshots, refresh, and rollback compatibility remain
  consistent.
- `api.services.list_vault_directories`, `VaultDirectoryInfo`, and
  `VaultDirectoryListResponse` as the starting point for workspace/vault file
  listing. Extend or share the directory-listing shape rather than building a
  second unrelated tree API.
- `static/js/workspace-picker.js` for lazy tree expansion and workspace-rooted
  modal behavior. The reference picker can share rendering helpers or be a
  sibling controller with the same fetch/toggle conventions.
- `static/js/workflow-actions.js` for modal shell, save button, SHA conflict
  handling, and textarea editing patterns. Extract common modal/file-editor
  helpers if generic vault-file editing starts duplicating workflow editing.
- `static/js/chat-rendering.js` post-processing hook after sanitized markdown
  render for vault-link upgrades. Keep link enhancement separate from markdown
  parsing and from model output requirements.
- `core/chat` tool-event storage already carries `artifact_ref`; evaluate
  whether it can index UI artifacts before adding a separate chat-artifact
  table.

## Validation Targets

Agents should use targeted local checks while developing and ask maintainers to
run full validation.

Phase 1 validation targets:

- API endpoint scenario extending the existing integration API coverage:
  - read a markdown file by vault-relative path;
  - reject path traversal;
  - save with matching hash;
  - reject stale hash;
  - verify vault-state mutation row is recorded.
- Frontend smoke/manual check:
  - reference picker opens from composer;
  - workspace and vault-wide search both work;
  - selected references insert into the prompt;
  - file links open the modal;
  - save conflict message is visible.

Phase 2 validation targets:

- API/service scenario for applying selected edit proposals with hash checks.
- UI smoke/manual check for proposal card selection, apply, conflict, and reload
  behavior.

## Next Implementation Steps

1. Define the generic vault file read/write API models and service helpers.
2. Add targeted API coverage for read/write path safety and hash conflicts.
3. Build the file modal using the existing workflow editor modal as the local
   pattern.
4. Add composer reference state and a reference picker rooted in workspace with
   vault-wide search.
5. Upgrade recognized vault file paths in assistant messages into openable file
   links.
6. Continue Phase 2 hardening around proposal rendering, conflict display, and
   richer edit operation shapes.

## Implementation Status

Current branch slice:

- Added generic vault file read/write API models and routes:
  - `GET /api/vaults/{vault_name}/files?path=...`
  - `PUT /api/vaults/{vault_name}/files?path=...`
- Added `GET /api/vaults/{vault_name}/file-refs` for workspace/vault reference
  listing and search.
- Added `static/js/file-references.js` to own:
  - composer reference picker modal;
  - insertion of `@vault/path.md` references into the chat input;
  - reusable vault file modal with hash-checked save;
  - missing-file create flow for referenced files that do not exist yet;
  - assistant-message vault path enhancement.
- Wired the chat composer with an Add File Reference button.
- Wired assistant markdown post-processing to upgrade recognized vault text paths
  and markdown file links into modal-opening controls.
- Added the first Phase 2 collaborative edit proposal slice:
  - `propose_file_edits` tool creates server-owned proposal artifacts;
  - proposal artifacts are stored with the owning chat session;
  - tool events expose `artifact_ref` for persisted and live rendering;
  - `GET /api/vaults/{vault_name}/chat/{session_id}/edit-proposals/{artifact_ref}`
    fetches proposal cards;
  - `POST /api/vaults/{vault_name}/chat/{session_id}/edit-proposals/{artifact_ref}/apply`
    applies approved existing-file text replacements with hash checks;
  - `static/js/edit-proposals.js` renders collapsible review cards with
    approve/comment/deny row decisions, comment prompts, and editable replacement
    text.
  - review prompt instructions are built from `core/constants.py` by the backend
    review endpoint; `display_prompt` keeps chat history concise.

Known Phase 1 follow-ups:

- Add `@path` autocomplete in the text input; the current slice has the modal
  picker and serialized `@path` references, but not inline autocomplete.
- Consider extracting shared modal/editor helpers if workflow editing and vault
  file editing continue to converge.
- Consider pruning hidden directories during recursive search traversal rather
  than only filtering hidden results after discovery.
- Consider a richer missing-file affordance that distinguishes "create this
  file" suggestions from likely typo/bad-path references before opening the
  editor.
- Add browser-level smoke coverage when a Playwright/browser test harness is
  available in the environment.

Known Phase 2 follow-ups:

- Extend edit proposal artifacts beyond existing-file text replacement with an
  explicit operation field. Candidate operation kinds:
  - `replace_text`: current implemented behavior; existing file, exact
    `original_text` match, hash check, replacement text.
  - `create_file`: proposed new vault path plus full initial content; apply
    should fail if the file already exists unless the proposal explicitly
    supports overwrite.
  - `delete_file`: proposed existing vault path, captured hash, preview/snippet,
    and apply-time hash check before deletion.
  - `move_file`: proposed source and destination paths, source hash check,
    destination existence check, and normal vault-state move recording.
  Each operation should render with operation-specific UI while preserving the
  same per-row approve/comment/deny review model.
- Add browser-level coverage for proposal card rendering, edited replacement
  text, conflict display, and reload behavior when a frontend harness is
  available.
- Support richer edit operation shapes after the exact replacement contract has
  been exercised in real use.
- Decide whether local existing `system/settings.yaml` files should be repaired
  automatically to include newly registered default chat tools such as
  `propose_file_edits`, or whether the settings repair action remains the
  explicit upgrade path.
