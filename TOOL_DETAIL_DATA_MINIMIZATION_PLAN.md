# Tool Detail Data Minimization Plan

## Objective

Keep tool arguments and results out of ordinary eager chat-session and live tool-lifecycle payloads. The tool list will show only the tool name and lifecycle status. Complete details will be returned only by the authenticated per-call detail endpoint after the user opens a tool modal, and client-held detail references will be cleared when the modal closes. Deferred-review payloads remain a deliberate exception because users need the proposed arguments to make and edit approval decisions.

## Scope and invariants

- Replace persisted-session `tool_events` with effective-history `tool_calls` summaries containing only the call ID, tool name, and terminal state.
- Remove arguments, results, result metadata, artifact references, and code detail from live `tool_call_started` and `tool_call_finished` browser events.
- Preserve complete tool-event persistence and the authorized per-call detail response.
- Restrict the ordinary detail endpoint to calls retained in effective chat history; archived raw events remain server-side for a future dedicated audit surface.
- Fail closed when a tool-call ID is reused or maps to multiple stored invocation rows, preventing details from different generations from being combined.
- Preserve arguments in the separate deferred-review contract so approval decisions remain informed.
- Remove argument previews and tool-result-derived artifacts from the tool list.
- Abort an in-flight detail request on modal close, clear all entry-held detail values, invalidate late responses, and explicitly request details with `cache: "no-store"`. The application-wide API response policy already sets `Cache-Control: no-store`.
- Do not claim secure memory erasure in JavaScript; clearing references and removing the modal bounds ordinary browser retention while garbage collection remains implementation-controlled.
- Preserve raw tool history server-side for the future audit view.

## Affected areas

- `api/models.py` and `api/services/chat_sessions.py`: define and build the minimal tool-call summary contract, filtered to effective history.
- `core/chat/task_execution.py`: minimize browser-facing task events while retaining server-side logging and persisted tool details.
- `static/js/chat-rendering.js`: render name/status-only tool rows, wait for canonical persistence before loading live-call details, lazy-load modal details, and clear them on close.
- Validation scenarios: update persisted replay expectations and assert that eager session and stream payloads exclude confidential fields while on-demand detail remains complete.

## Validation targets

- Extend `integration/core/chat_tool_replay_contract` to verify effective summaries are minimal, archived/orphan calls are excluded, and the detail endpoint still returns full arguments and results.
- Update tool-stream scenarios to verify lifecycle metadata remains available while arguments, results, and result metadata are absent from browser events.
- Run JavaScript syntax checks, the affected individual scenarios, Ruff, Black, and MyPy. Maintainers retain ownership of the full integration profile.

## Implementation sequence

1. Introduce the safe tool-call summary response and effective-history filtering.
2. Minimize live task event payloads to identity and lifecycle metadata.
3. Simplify tool-list rendering and implement abort-and-clear modal behavior.
4. Update focused validation contracts and run targeted checks.

## Next phase

Proceed to Feature Development, followed by focused Testing and Validation and Commit and Review Prep.
