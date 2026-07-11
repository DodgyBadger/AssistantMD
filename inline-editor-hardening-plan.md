# Inline Editor Hardening Plan

## Objective

Harden the `dev/inline-editor` branch before merge without changing its product
direction: chat-native vault references, one unified vault tree/file modal,
consolidated `file_read` and `file_write` tools, and optional inline edit
review backed by Pydantic AI deferred tools.

This plan follows the contract-first smell framework in
`docs/agent-guides/refactor-and-hardening.md`. Correctness and lifecycle fixes
precede structural cleanup.

## Invariants

1. A vault name and every vault-relative path must remain inside a configured
   vault root after symlink resolution.
2. One deferred review can resume at most once. Its resumed task must obey the
   same per-session ordering as an ordinary chat turn.
3. Approved, denied, and failed review outcomes must remain understandable in
   canonical chat history and durable review state.
4. Collaborative approval must not silently overwrite, move, or delete a file
   that changed materially while review was pending.
5. Workflows, context scripts, delegates, and code execution must never block on
   interactive approval, but app-wide disabled tools must remain unavailable on
   every execution surface.
6. All writes must use shared vault mutation helpers and preserve mutation
   audit, snapshots, refresh, and rollback behavior.
7. The unified explorer must make every eligible child reachable, reject stale
   async responses, and behave consistently from every entry point.
8. Historical records may remain readable after temporary tools are retired,
   but retired mutation and prompt-building paths must not remain executable
   without an explicit compatibility requirement.

## Review Findings

### Critical

#### H-01: API vault-name resolution does not enforce the data-root boundary

- **Smell:** bypass path / missing boundary validation.
- **Evidence:** `api.services._resolve_vault_root()` resolves
  `data_root / vault_name` and checks only `is_dir()`; it does not call
  `relative_to(data_root)` or validate against configured vault identities.
- **Consequence:** `..`, dot segments accepted by a caller, or a symlink under
  the data root can resolve outside the vault collection. The new file read,
  write, explorer, listing, search, and path-resolution APIs all trust this
  helper.
- **Correction:** introduce one authoritative configured-vault resolver that
  normalizes the name, rejects separators/dot names, proves containment after
  resolution, and rejects symlinked roots that escape the data root. Route all
  API and chat-surface vault lookup through it.

### High

#### H-02: Deferred review submission starts work before claiming the review

- **Smell:** invalid lifecycle state / check-then-act race.
- **Evidence:** `submit_chat_deferred_review()` starts the resume task before
  `mark_deferred_review_submitted()` updates the row. The database update itself
  performs a separate read and does not claim with an atomic
  `UPDATE ... WHERE status = 'pending'`.
- **Consequence:** concurrent submissions can launch multiple resumed agents.
  The losing request returns a conflict only after its background task exists
  and may already be mutating files.
- **Correction:** atomically reserve the pending review before any task starts.
  Use explicit `pending -> resuming -> completed|failed` states and a
  compare-and-set update. If task creation fails, record a recoverable failure
  state instead of returning the row to ambiguous pending state.

#### H-03: Deferred resumes bypass the per-session chat queue

- **Smell:** bypass path / temporal coupling.
- **Evidence:** ordinary chat uses `start_queued_chat_stream_task()` and a
  session execution gate. `start_deferred_review_resume_task()` delegates to
  `start_prepared_chat_stream_task()`, which starts immediately without that
  gate.
- **Consequence:** approving a review can overlap a prompt queued or started
  after the review card appeared. Both runs can append history and mutate vault
  files against incompatible session state.
- **Correction:** add a queued prepared/resume task path using the same session
  gate. Define whether a review resume is ordered at submission time or retains
  priority from its originating turn; use submission order initially because it
  is deterministic and matches current user expectations.

#### H-04: Collaborative overwrite, move, and delete lack a review-time base

- **Smell:** stale state / partial inline edit contract.
- **Evidence:** deferred review persists model tool arguments only. The
  `file_write` schema has no expected hash, and full overwrite calls
  `replace_vault_file_content()` without a concurrency check. Move and delete
  similarly execute against whatever exists when approval resumes.
- **Consequence:** changes made in Obsidian, the inline editor, or another task
  while the card is pending can be silently overwritten, moved, or deleted.
  Snapshots make recovery possible but do not prevent incorrect approval.
- **Correction:** enrich deferred file-write requests server-side with current
  path facts and hashes when the review artifact is created. On resume, validate
  the captured hash for destructive existing-file operations. Exact replacement
  and line-edit operations should retain their content checks; append and mkdir
  need operation-specific semantics rather than a blanket hash rule.

### Medium

#### H-05: Deferred review state never records resume completion or failure

- **Smell:** incomplete lifecycle / dead schema fields.
- **Evidence:** records transition only from `pending` to `submitted`.
  `error_json` is stored and loaded but never written, and resumed task terminal
  state is not reflected in the review row.
- **Consequence:** reloads show a permanently generic Submitted card even when
  the resumed task failed or was cancelled. Operators cannot reliably correlate
  review state with its outcome.
- **Correction:** update review status from task completion hooks and persist a
  bounded result/error summary. Render `resuming`, `completed`, `failed`, and
  `cancelled` distinctly.

#### H-06: The explorer silently makes entries beyond 100 unreachable

- **Smell:** lossy API contract.
- **Evidence:** `file-refs` clamps both child listing and search to 100 items,
  while `VaultFileReferenceListResponse` has no `truncated`, cursor, or total
  field. The tree reports only "Showing 100 items."
- **Consequence:** a folder with more than 100 visible children is not fully
  browsable, contradicting the vault explorer contract.
- **Correction:** add deterministic pagination or a continuation cursor for
  direct child listing and expose truncation explicitly. Search can remain
  bounded but must report truncation and offer a refinement message.

#### H-07: Explorer search has stale-response and unhandled-error paths

- **Smell:** async race / incomplete failure handling.
- **Evidence:** debounced input and scope changes call `loadResults()` without a
  request generation or `AbortController`; only the initial load has a terminal
  catch. A slower earlier response can overwrite newer results, and later fetch
  failures can become unhandled promise rejections.
- **Consequence:** tree results can disagree with the visible query/scope, or
  remain blank/loading after transient failures.
- **Correction:** give the picker one request lifecycle controller, abort or
  ignore stale generations, preserve the last successful result until the next
  request wins, and render retryable errors consistently.

#### H-08: The deferred card lost shared vault-navigation affordances

- **Smell:** contract drift / duplicated UI implementation.
- **Evidence:** deferred file paths render as inert spans, and move destinations
  use a plain text input. The retired proposal renderer had open-file links and
  the shared path selector.
- **Consequence:** inline edit review no longer provides the file inspection
  and destination selection behavior established elsewhere in the unified
  modal.
- **Correction:** make reviewed paths open the unified file/tree modal and reuse
  the shared destination picker for move. Keep operation-specific field
  rendering, but extract common review-card state and controls where it reduces
  actual duplication.

#### H-09: Retired edit-proposal execution remains live beside deferred review

- **Smell:** obsolete parallel architecture / speculative compatibility.
- **Evidence:** the temporary tools are retired, but `core/chat/edit_proposals`,
  mutating/review API endpoints, the frontend controller, prompt builders, and
  schema remain active. Release notes and ADR 0023 state that inline edit
  review is provided exclusively through deferred `file_write`.
- **Consequence:** two review state machines and mutation paths must be
  maintained, and historical pending artifacts can still invoke the retired
  prompt-based workflow.
- **Correction:** determine whether production data contains historical
  proposal artifacts. Preserve a read-only historical renderer if required;
  remove creation, apply, review, deny, prompt-building, and executable frontend
  submission paths. Remove the table only through an explicit migration policy.

#### H-10: External tool-policy bypass (not reproduced)

- **Initial concern:** `ChatSurfaceRequest` accepts a caller-provided `tools`
  list instead of resolving the web chat defaults itself.
- **Review result:** every surface still reaches shared `resolve_tool_binding()`,
  which rejects unknown or globally disabled tools using
  `get_enabled_tools_config()`. The requested list can narrow enabled tools but
  cannot widen them.
- **Disposition:** no policy layer is added. Keeping enforcement in shared tool
  binding avoids duplicating enabled-tool filtering across surfaces.

#### H-11: Tool binding converts implementation `TypeError` into parameter error

- **Smell:** lossy error translation.
- **Evidence:** `_wrap_tool_function()` catches every `TypeError` raised while
  invoking a tool and returns `invalid_parameters`.
- **Consequence:** a real programming defect inside `file_read`, `file_write`,
  or another tool is misreported to the model and hidden from task failure
  handling.
- **Correction:** rely on Pydantic AI schema validation for call-shape errors, or
  bind arguments before invocation and catch only binding failures. Let internal
  `TypeError` propagate with normal diagnostics.

### Low / Structural

#### H-12: New orchestration functions are already crossing complexity limits

- **Smell:** mixed responsibility / divergent change.
- **Evidence:** the initial scan identified `submit_chat_deferred_review()` at
  complexity 16 and `mutate_vault_path()` at 11. The central streaming task
  runner remains an older hotspot outside this focused refactor.
- **Consequence:** lifecycle and translation changes require editing large
  branch-heavy functions, increasing regression risk.
- **Correction:** after behavior is hardened, split validation, state
  transition, task construction, operation dispatch, and response translation
  into focused helpers. Do not add forwarding-only service layers.

## Implementation Stages

## Outcome

The hardening pass implemented H-01 through H-09 and H-11. H-10 was closed as
not reproducible because shared tool binding already enforces app-wide enabled
tools. H-12 was addressed for the newly expanded deferred-review submission
path; older complexity hotspots remain outside this branch's focused refactor.

Targeted scenarios cover vault-root containment and explorer pagination,
atomic review submission, session queue ordering, stale reviewed targets,
terminal review states, historical proposal compatibility, inline edit tool
policy, unified file operations, API endpoints, external chat surfaces, and
vault mutation recording. Frontend syntax checks pass. Browser-level visual,
focus, mobile, and rapid-search checks remain part of live review.

### Stage 1: Boundary And Race Regression Scenarios

Add failing assertions before implementation:

- reject dot, parent, separator, absolute, and escaping-symlink vault names for
  every new vault API family;
- submit the same review concurrently and prove exactly one resume task exists;
- queue a normal prompt and a review resume in one session and prove serialized
  history/task execution;
- modify a reviewed overwrite/move/delete target before approval and require a
  conflict without mutation.

### Stage 2: Authoritative Vault Resolution

- Add one shared configured-vault resolver below API/tool adapters.
- Replace direct `data_root / vault_name` construction in changed interactive
  entry points.
- Keep vault-relative path validation in `core.vault_state.pathing` and avoid a
  second normalization implementation.
- Add stable error codes for invalid vault name, unknown vault, and escaped
  vault root.

### Stage 3: Deferred Review State Machine And Queue

- Introduce explicit review statuses and atomic compare-and-set transitions.
- Reserve the review before task creation and make repeated submissions
  idempotently return or reject without starting work.
- Start resumed execution through the session gate.
- Persist terminal task outcome and bounded diagnostics on the review.
- Add lifecycle events for claim, resume start, completion, cancellation, and
  failure.

### Stage 4: Collaborative Concurrency Contract

- Define operation-specific review snapshots for `file_write`.
- Capture current hashes and existence state for overwrite, move, and delete.
- Validate snapshots immediately before mutation through core vault operation
  helpers, not in the frontend.
- Include conflict facts in the tool result and review card without leaking file
  content into logs.
- Decide and document append semantics when the target changes while pending.

### Stage 5: Explorer Completeness And Async Lifecycle

- Add paginated child listing and explicit search truncation.
- Add abort/generation handling to picker requests.
- Consolidate picker load, refresh, reveal, and error state.
- Restore deferred-card file links and shared move destination selection.
- Add browser checks for large folders, rapid search changes, failures, mobile,
  dark mode, focus, and dirty editor navigation.

### Stage 6: Retired Path Removal

- Inspect persistent databases for `chat_edit_proposals` rows and statuses.
- Keep only the minimum read-only compatibility renderer required for historical
  sessions.
- Remove retired proposal mutation/review endpoints, prompt builders, controller
  submission code, and unused models.
- Remove stale CSS only after both deferred and historical cards are visually
  verified.

### Stage 7: Structural Refactor And Documentation

- Split complex orchestration after scenario coverage is green.
- Correct TypeError handling in shared tool binding.
- Enforce enabled tools in the external surface adapter.
- Align ADR, architecture docs, release notes, and implementation plans with the
  resulting current contract.
- Run duplication and dead-code searches for retired tool names and proposal
  artifacts.

## Validation Ownership

Agents should run focused scenarios and fast structural checks while each stage
is implemented. Maintainers should run the full validation suite before merge.

Focused scenario targets:

- `integration/core/deferred_review_task_skeleton`
- `integration/core/chat_task_session_queue`
- `integration/core/file_ops_inline_edit_policy`
- `integration/core/file_ops_unified_tool`
- `integration/core/vault_file_reference_api`
- `integration/core/vault_state_mutation_recorder`
- a new configured-vault-boundary scenario
- a new deferred-review concurrency and stale-target scenario

Keep `scripts/check_vault_mutation_routing.py`, Python compilation, Ruff, JS
syntax checks, and `git diff --check` in the fast feedback loop.

## Review Baseline

At plan creation, the following focused scenarios pass:

- `integration/core/deferred_review_task_skeleton`
- `integration/core/file_ops_unified_tool`
- `integration/core/vault_file_reference_api`

The vault mutation routing guard, Python compilation, Ruff default checks, JS
syntax checks, and `git diff --check` also pass. These confirm the current happy
path; they do not cover the critical and high-severity cases above.
