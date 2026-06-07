# Frontend Refactor Plan

## Goal

Reduce `static/app.js` from a single large coordinator into a small app shell plus focused frontend modules, without changing the user-visible behavior or introducing a frontend framework prematurely.

The ideal end state is:

- `static/index.html` contains page structure only.
- `static/app.css` contains application-specific CSS.
- `static/app.js` is a coordinator under roughly 1,000-1,500 lines.
- Feature modules own rendering and event handling for their own UI surfaces.
- Shared helpers live in explicit shared modules, not copied across modules.
- Modules receive dependencies explicitly instead of reaching across hidden globals where practical.

## Current State

As of this plan:

- `static/app.js`: about 4,373 lines.
- `static/index.html`: about 749 lines after CSS extraction.
- `static/app.css`: about 1,514 lines.
- `static/js/configuration.js`: about 2,596 lines, already separate.
- `static/js/session-summary.js`: about 427 lines, newly extracted.
- `static/js/icons.js` and `static/js/utils.js`: shared frontend helpers.

`app.js` still owns many unrelated concerns:

- chat shell state and controls
- workspace picker
- session selector and compaction status
- dashboard rendering
- vault activity rendering
- chat sending, streaming, markdown rendering, tool-call UI
- session export/delete/title operations
- workflow operations
- app initialization and event delegation

## Design Principles

- Keep `app.js` as the app coordinator until the module boundaries are stable.
- Do not introduce React/Vue/Svelte as part of this refactor. Reassess after modularization.
- Prefer plain scripts loaded in dependency order for now, matching the existing `configuration.js` pattern.
- Avoid duplicating state ownership. One module should own each UI behavior.
- Pass dependencies into modules explicitly:
  - `state`
  - relevant element registry
  - shared `utils`
  - shared `icons`
  - callbacks for app-owned actions such as `fetchSessions`
- Keep commits small enough to review and revert independently.
- Avoid behavior changes unless a refactor reveals an actual bug.

## Proposed Module Shape

Keep:

- `static/app.js`
  - app boot
  - shared state object
  - high-level element registries
  - tab switching
  - top-level refresh orchestration
  - remaining glue while modules are being extracted

Existing shared modules:

- `static/js/icons.js`
  - inline SVG constants and typing dots
- `static/js/utils.js`
  - escaping, truncation, date formatting, copy helpers
- `static/js/session-summary.js`
  - session summary preview/modal

Target modules:

- `static/js/workspace-picker.js`
  - workspace path controls
  - workspace unlock
  - workspace picker modal
  - folder tree loading/rendering

- `static/js/session-controls.js`
  - session dropdown
  - session title row
  - session export/delete/save title
  - compaction progress display
  - should depend on `session-summary.js`, not duplicate its summary logic

- `static/js/chat-streaming.js`
  - send message flow
  - streaming SSE parsing
  - assistant message rendering
  - tool-call rendering
  - copy/fork controls
  - markdown/math post-processing hooks

- `static/js/dashboard-view.js`
  - system status rendering
  - vault table
  - workflow table
  - dashboard sorting
  - running workflow task summary

- `static/js/vault-activity.js`
  - vault activity loading/rendering
  - activity details modal
  - mutation sorting

- `static/js/workflow-actions.js`
  - rescan vaults
  - workflow enable/disable
  - workflow file editor
  - manual execute/stop/monitor workflow task

Potential later shared modules:

- `static/js/api.js`
  - small fetch helpers only if repeated request patterns become noisy
- `static/js/dom.js`
  - event delegation helpers only if multiple modules need the same patterns
- `static/js/markdown.js`
  - Markdown, MathJax, DOMPurify helpers if chat streaming extraction benefits from it

## Implementation Sequence

### Phase 1: Complete Low-Risk Structure

Status: complete in the current refactor branch.

- Extract inline CSS into `static/app.css`.
- Extract icons into `static/js/icons.js`.
- Extract shared utilities into `static/js/utils.js`.
- Extract session summary preview/modal into `static/js/session-summary.js`.

Next checks:

- Confirm the app still loads all scripts in the correct order. Done by script-order inspection and `node --check`.
- Confirm no helper is duplicated between `app.js` and the new modules. Done for extracted helpers.

### Phase 2: Extract Workspace Picker

Status: complete in the current refactor branch.

Why next:

- It is cohesive and mostly independent.
- It has a clear modal/tree boundary.
- It should remove roughly 200-250 lines from `app.js`.

Move:

- `syncWorkspaceControlState`
- `currentWorkspacePath`
- `saveWorkspacePath`
- `unlockWorkspacePath`
- `openWorkspacePickerModal`
- `closeWorkspacePickerModal`
- `loadWorkspaceDirectory`
- `fetchWorkspaceDirectories`
- `toggleWorkspaceTreeNode`
- `renderWorkspaceDirectoryRow`

Keep in `app.js`:

- `state.isWorkspaceUnlocked`
- calls that need current workspace value during send
- event wiring until the module owns it cleanly

Validation target:

- Manual smoke: unlock/edit workspace, open picker, expand folder tree, select workspace, start/load session.
- Static checks: `node --check` for all scripts and `git diff --check`. Done.

### Phase 3: Extract Session Controls

Status: complete in the current refactor branch.

Why:

- Session dropdown logic is related to summary but should not live inside summary module.
- It is a good second UI-control extraction after workspace picker.

Move:

- session dropdown open/close
- session title formatting
- session activity label formatting
- session selector rendering
- session dropdown row rendering
- session summary trigger visibility
- session title save/export/delete if the boundary stays clean
- compaction progress rendering if session controls remain the right owner

Dependencies:

- `session-summary.js`
- app callback for `loadSession`
- app callback for `clearSession`
- app callback for `fetchSessions`

Validation target:

- Manual smoke: select existing session, new session, summary peek, summary modal, title save, export/delete buttons.
- Static checks: `node --check` for all scripts and `git diff --check`. Done.

### Phase 4: Extract Dashboard View

Status: complete in the current refactor branch.

Why:

- Large reduction with relatively clear data-in/render-out logic.
- Dashboard rendering is mostly independent from chat runtime.

Move:

- `displaySystemStatus`
- dashboard vault/workflow rendering
- dashboard sorting and comparison helpers
- running workflow task rendering

Keep in `app.js` initially:

- polling orchestration
- metadata/system-status fetch orchestration

Validation target:

- Manual smoke: dashboard loads, sort headers work, workflow run buttons still dispatch, running tasks display.
- Static checks: `node --check` for all scripts and `git diff --check`. Done.

### Phase 5: Extract Vault Activity

Status: complete in the current refactor branch.

Why:

- Related to dashboard but complex enough to deserve its own module.

Move:

- vault activity loading/rendering
- activity kind labels/icons
- details modal
- mutation sorting and modal event handling

Validation target:

- Manual smoke: vault activity loads, sorting works, details modal opens/closes.
- Static checks: `node --check` for all scripts and `git diff --check`. Done.

### Phase 6: Extract Workflow Actions

Status: complete in the current refactor branch.

Why:

- Action-heavy but not deeply tied to chat rendering.

Move:

- rescan
- workflow enable/disable
- file editor modal
- execute workflow
- monitor task
- stop workflow / stop all
- render workflow task result

Validation target:

- Manual smoke or targeted scenario if available: run workflow, stop workflow, edit workflow file.
- Static checks: `node --check` for all scripts and `git diff --check`. Done.

### Phase 7: Extract Chat Streaming

Status: next.

Why last:

- Highest risk and most central behavior.
- Touches active API calls, SSE parsing, message rendering, markdown, tool calls, copy/fork, and scroll behavior.

Move:

- `sendMessage`
- SSE event parsing
- assistant streaming message creation
- tool call rendering
- assistant finalization
- markdown/math post-processing if needed
- copy/fork button helpers if not already in shared utilities

Keep in `app.js`:

- state object initially
- high-level send button wiring initially
- vault/session/workspace selection inputs

Validation target:

- Manual smoke: send basic message, send message with tool calls, stop response, copy response, fork from assistant message.
- If validation coverage exists for chat streaming, extend that scenario rather than adding a separate noisy one.

## Framework Decision Point

Reassess a frontend framework only after Phases 1-5 are complete.

Consider a framework only if:

- module boundaries still require too much manual DOM synchronization
- state updates remain fragile across modules
- UI components repeatedly reimplement lifecycle/render patterns
- testing frontend behavior remains difficult due to manual DOM mutation

Do not migrate solely because file size is large. The first target is clearer ownership and lower drift risk.

## Validation Policy

For each extraction:

- Run `node --check` for all changed frontend scripts.
- Run `git diff --check`.
- Perform a targeted browser smoke check when the refactor touches visible UI behavior.
- Do not run the full validation suite unless maintainers request it.

Suggested recurring command:

```bash
node --check static/js/icons.js \
  && node --check static/js/utils.js \
  && node --check static/js/session-summary.js \
  && node --check static/app.js \
  && git diff --check
```

Extend this command as new scripts are added.

## Next Concrete Step

Extract `static/js/workspace-picker.js` using the same controller pattern as `session-summary.js`.

The first implementation pass should:

1. Move workspace picker functions into the new module.
2. Load the script before `static/app.js`.
3. Instantiate the module from `app.js` with explicit dependencies.
4. Replace direct function references in event handlers with module methods.
5. Run syntax and whitespace checks.
6. Do a manual smoke check of workspace selection.
