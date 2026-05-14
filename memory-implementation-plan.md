# Memory Implementation Plan

## Current Architecture Read

Relevant existing contracts:

- `core/chat/chat_store.py` persists canonical chat sessions in
  `system/chat_sessions.db`, keyed by globally unique `session_id` and hard
  scoped to `vault_name`.
- `core/chat/executor.py` performs chat preflight, runs context assembly through
  chat capabilities, persists the accepted user request before model execution,
  persists new assistant/tool messages after completion, and handles streaming
  and non-streaming paths separately after shared preflight.
- `core/authoring/context_manager.py` runs the selected context template as a
  Monty history processor. Context scripts receive prior history and
  `latest_message`, then return assembled context through `assemble_context`.
- `core/authoring/runtime/monty_runner.py` exposes all configured tools as direct
  Monty functions, excluding only `code_execution`. Therefore `memory_ops` can
  be called from context scripts once it is present in tool configuration.
- `core/memory/service.py` is currently a conversation-history broker. It is the
  right domain boundary to grow into workstream operations, but existing
  conversation-history behavior should remain stable.
- `core/tools/memory_ops.py` exists as an optional tool, but the current settings
  template does not register it. Docs describe it as disabled by default.
- `core/vault_state/` tracks vault manifests, AssistantMD-routed mutations, and
  task-scoped file mutation rows. It is useful for outputs/files modified, but
  it does not currently track every file read or retrieved.
- `docs/architecture/authoring-engine.md` distinguishes direct tools from
  built-in helpers. Memory should use the direct tool path, not a parallel
  helper contract.

Design invariants:

- The selected vault is a hard scope. Workstream matching should not cross vaults
  unless a future feature explicitly opts into cross-vault memory.
- Session-to-workstream linking is context-policy controlled. A chat session may
  be unlinked when memory is disabled, when there is not enough signal yet, or
  when the user chooses an incognito/no-memory context policy.
- A linked chat session belongs to at most one current workstream. Relinking
  is explicit, auditable, and vault-scoped.
- `memory_ops` is the canonical operation surface for chat agents and authored
  scripts. Do not create a second helper API with a separate contract.
- Default adaptive behavior should use the same `memory_ops` operations available
  to context scripts.
- Inferred fields are candidates. User-confirmed fields and source vault files
  carry stronger trust.
- Retrieval is field-aware. Exact and semantic matching should compare like
  fields to like fields (`topic` to `topic`, `type` to `type`, `strategy` to
  `strategy`) because each field encodes a different kind of relationship.
  Cross-field aggregation can happen after retrieval, but raw matches should
  preserve their field channel and reason.
- This feature is experimental. Each major slice should include a small product
  experiment, not only unit/integration validation, and later slices should
  adjust based on what those experiments show.

## Iteration Model

Memory should be built as a sequence of reversible experiments. For each slice:

- Define the technical contract being added.
- Add focused automated tests for that contract.
- Run a small scenario experiment against realistic vault/chat examples.
- Record what the experiment shows, including confusing or low-value behavior.
- Decide whether to proceed, adjust the data model/policy, or defer the next
  slice.

Experiment notes should live alongside this plan until the shape stabilizes,
then move into architecture/product docs only when they describe current
contract.

Initial scenario set:

- Donor/client report: a new report should find prior format/source/context
  candidates without confusing reports for different subjects.
- Annual goals and performance review: recurring work should surface durable
  goals, themes, and artifacts over time.
- Pure retrieval: a quick "where did I mention X?" chat should not become
  high-authority memory by default.
- Snippet folder synthesis: a collection of saved material should be available
  as source context without pretending every transient note is a durable
  conclusion.
- Incognito/no-memory: a session should be able to use normal chat/context
  behavior without linking or writing workstream state.

Decision checkpoints:

- After Slice 0: confirm the vector provider/model/settings contract is reusable
  outside memory and can be validated without real provider calls.
- After Slice 3: confirm the persistence/tool contract is understandable enough
  for authored scripts before wiring default behavior.
- After Slice 5: inspect actual captured signals and decide whether the current
  fields are too noisy, too sparse, or missing important dimensions.
- After Slice 8: test whether related workstream suggestions are useful enough to
  justify default memory-aware context assembly.
- Before Slice 10: decide whether LLM extraction is needed, and if so what it
  should be allowed to infer.

## Slice 0: Shared Vector Embedding Plumbing

Goal: add reusable provider/model/settings plumbing for embeddings before memory
stores or queries vectors. This should be a general service that any subsystem
can call, not a memory-specific shortcut.

Pydantic AI read:

- The installed Pydantic AI version exposes `pydantic_ai.Embedder` as the
  high-level embedding interface.
- `Embedder` supports `embed_query(...)` and `embed_documents(...)`, returning
  `EmbeddingResult` with vectors, input type, model/provider names, usage, and
  provider details.
- Built-in embedding models include `OpenAIEmbeddingModel`; it accepts an
  `OpenAIProvider(api_key=..., base_url=...)`, which matches the current
  provider/secret pattern used by chat model construction.
- `EmbeddingSettings` supports dimensions and provider options.
- `TestEmbeddingModel` provides deterministic validation without real provider
  calls.

Recommended contract:

- Add a `core.vector` or `core.embeddings` service boundary. Prefer
  `core.vector` if the service will own both embedding generation and vector
  storage helpers; prefer `core.embeddings` if storage remains entirely with
  consumers.
- Use the existing `models` section for embedding aliases. Embedding models are
  regular model entries with `capabilities: ["embedding"]` and an explicit
  `dimensions` value.
- Provider entries continue to hold `api_key` and `base_url` secret pointers.
- Do not expose embedding-only aliases as chat-capable models; `["embedding"]`
  must remain embedding-only rather than silently gaining `text`.
- Reuse the existing secrets store; do not introduce new secret storage.
- Build an embedder factory that resolves provider/model config and constructs
  Pydantic AI embedding models.
- Provide service methods:
  - `embed_query(text, model_alias="default")`
  - `embed_documents(texts, model_alias="default")`
  - `cosine_similarity(left, right)`
  - optional `fingerprint_text(text)` for cache keys
- Return a local result type that preserves vectors plus provider/model metadata
  without exposing provider-specific response objects to callers.
- Compute an `embedding_space_id` from provider, resolved base URL, model string,
  and dimensions. Vector comparisons must only happen within the same embedding
  space.

Storage guidance:

- Slice 0 should provide a vector-store abstraction with `upsert(...)` and
  `search_similar(...)`, so memory does not depend on whether similarity search
  is Python cosine, `sqlite-vec`, or another backend.
- The first implementation can use ordinary SQLite rows and Python cosine.
- Memory can then create a namespace for workstream field vectors keyed by
  field id, model alias, input text fingerprint, dimensions, vector blob/json,
  created_at, and provider metadata.
- Full vault-level vector indexing remains out of scope.

Validation:

- Unit/smoke test using Pydantic AI `TestEmbeddingModel` to prove query/document
  calls, dimensions, metadata, and usage are handled.
- Settings test that an embedding alias resolves provider/model/secret pointers
  without requiring a populated real API key in validation.
- Error test for missing embedding provider config.
- Error test for returned vector dimensions that do not match configured
  dimensions.
- Vector-store test that rows from a different embedding space are not returned
  for a query.
- No real network/provider calls in default validation.

Experiment:

- Add a fixture-level vector smoke using `TestEmbeddingModel` first.
- Then optionally run a manual provider-backed smoke when secrets are configured.
- Use the memory scenario fields as example documents:
  - `topic: wetlands`
  - `topic: watershed protection`
  - `topic: riparian restoration`
  - `type: donor report`
  - `type: funding proposal`
- Confirm the service can support comparing query fields to stored workstream
  fields before memory owns vector ranking.

Risks:

- Pydantic AI embedding APIs are provider-capable, but the app's settings schema
  previously assumed model aliases were text-capable by default. Embedding-only
  aliases must not be allowed to look like chat models.
- Test embeddings are deterministic but not semantically meaningful; they prove
  plumbing, not retrieval quality.

Progress notes:

- Implemented `core.vector.VectorService` as a reusable Pydantic AI embedding
  wrapper.
- Kept embedding configuration in the existing `models` section using
  `capabilities: ["embedding"]` and explicit `dimensions`.
- Added default `embeddings` alias pointing to OpenAI
  `text-embedding-3-small` with 1536 dimensions.
- Updated settings/API model serialization to preserve `dimensions`.
- Changed capability normalization so embedding-only aliases do not silently
  gain `text`.
- Added `embedding_space_id` derived from provider, resolved base URL, model
  string, and dimensions; vector comparisons reject dimension mismatches.
- Added `VectorStore` protocol and `SQLitePythonVectorStore`, using plain SQLite
  storage plus Python cosine behind an upsert/search abstraction.
- Added `validation/scenarios/experiments/vector_embedding_service_probe.py`
  using Pydantic AI `TestEmbeddingModel`, with no network calls.

## Slice 1: Work Workstream Data Model And Experiment Harness

Goal: prove the underlying memory shape before building higher-level behavior.
This slice includes durable workstream records, synthetic chat/session fixtures, and
smoke experiments that test whether useful workstream fields can actually be
extracted and queried.

Storage recommendation:

- New system DB: `system/memory.db`, owned by `core.memory`.
- Register `memory` in `core/database.py`.

Initial tables:

- `workstreams`
  - `workstream_id`
  - `vault_name`
  - `title`
  - `status`
  - `weight`
  - `confidence`
  - `created_at`
  - `last_seen_at`
  - `metadata_json`
- `workstream_sessions`
  - `workstream_id`
  - `session_id`
  - `vault_name`
  - `linked_at`
  - `link_source`
  - `confidence`
- `workstream_fields`
  - `id`
  - `workstream_id`
  - `field_type` (`type`, `topic`, `person`, `organization`, `project`,
    `objective`, `strategy`)
  - `value`
  - `normalized_value`
  - `confidence`
  - `source` (`inferred`, `user_confirmed`, `system`)
  - `created_at`
  - `updated_at`
- `workstream_artifacts`
  - `id`
  - `workstream_id`
  - `vault_name`
  - `path`
  - `artifact_role` (`file_read`, `file_retrieved`, `file_modified`,
    `output_created`, `planning_note`)
  - `source`
  - `created_at`
  - `metadata_json`
- `workstream_feedback`
  - `id`
  - `current_workstream_id`
  - `related_workstream_id`
  - `action` (`accepted`, `rejected`, `ignored`, `relinked`)
  - `reason`
  - `created_at`
- `workstream_field_vectors`
  - `id`
  - `field_id`
  - `workstream_id`
  - `model_alias`
  - `input_text`
  - `input_fingerprint`
  - `dimensions`
  - `vector_json` or compact blob
  - `provider_name`
  - `model_name`
  - `created_at`
  - `metadata_json`

Vector policy:

- Store vectors for extracted workstream fields, not whole vault files.
- Vectorized fields should include at least `type`, `topic`, `objective`, and
  `strategy`. Exact fields such as people/orgs/projects still need exact
  normalized matching first.
- Vector search is field-aware. A query `topic` vector searches stored `topic`
  vectors; a query `type` vector searches stored `type` vectors. Retrieval
  should not collapse different fields into one undifferentiated similarity
  pool.
- Semantic field matches are candidate generators and should produce softer
  reasons than exact matches, for example `semantic_topic_similarity`.
- The first semantic experiment should specifically test that a wetlands report
  can be found as a candidate for watershed protection or riparian restoration
  work even when exact topic strings do not match.

Service API:

- `get_current_workstream(vault_name, session_id)`
- `create_workstream(vault_name, title=None, metadata=None)`
- `link_session_to_workstream(...)`
- `unlink_session_from_workstream(...)`
- `update_workstream_fields(...)`
- `list_workstream_artifacts(...)`

Experiment harness:

- Add a small fixture builder for isolated runtime roots that can populate:
  - synthetic vault files
  - `chat_sessions.db` sessions/messages
  - `memory.db` workstreams/fields/artifacts
  - optional `task_file_mutations` rows for AssistantMD-created outputs
- Keep the fixture data close to the initial scenario set:
  - two donor reports with the same format but different subjects
  - one wetlands funding proposal related by topic but not task type
  - annual goals, weekly plans, and performance review sessions
  - a one-off pure retrieval question
  - a snippets/research folder synthesis session
  - an incognito/no-memory session
- Add smoke commands/tests that can print or snapshot:
  - extracted candidate fields from a chat transcript
  - linked workstream rows
  - artifact rows
  - related-query candidates and reasons

Extraction prototype:

- Build only a local experimental extractor in this slice, not production chat
  behavior.
- Start with deterministic extraction from session title, latest prompt, simple
  path/artifact signals, and manually seeded expected fields.
- Optionally add an offline LLM extraction probe behind an explicit test flag or
  script so we can compare model output with expected fields without committing
  to runtime LLM extraction.
- Record mismatches between expected fields and extracted fields as product
  feedback on the data model.

Validation:

- Creating a workstream does not implicitly link a session.
- Linking a session to a workstream is idempotent.
- An unlinked session has no current workstream.
- A session cannot link to a workstream in another vault.
- Field updates preserve source/confidence and normalize exact fields.
- Persistence works with runtime `system_root` isolation.
- Fixture builder can create isolated synthetic chat sessions and workstreams
  without touching `/app/data` or `/app/system`.
- Extraction smoke tests produce stable candidate fields for seeded scenarios.

Experiment:

- Populate both synthetic workstreams and synthetic chat sessions, then run the
  extraction/query smoke tests before finalizing the schema.
- Check whether the current fields can represent the important distinctions:
  same task type vs same topic, same entity vs different subject, durable work
  vs one-off retrieval, linked vs incognito.
- Inspect whether extracted values are useful as query dimensions or whether
  they collapse into vague labels.
- Compare exact field matching with vector-backed field matching for related
  concepts like wetlands, watershed protection, and riparian restoration.
- Adjust table shape if the source/confidence/artifact model is awkward to
  explain, extract, or query.
- Treat this as the highest-feedback slice; do not move to the `memory_ops`
  refactor until the data model survives these scenario probes.

Progress notes:

- Initial implementation added `system/memory.db` schema registration, a
  `WorkstreamStore`, synthetic scenario fixture harness, deterministic
  extraction prototype, explainable related-workstream query, and
  `scripts/memory_workstream_smoke.py`.
- Added `validation/scenarios/experiments/memory_workstream_data_model_probe.py`
  so maintainers have a scenario entry point for the same data-model probe.
- First smoke run caught an overly broad organization extractor; it was
  tightened to avoid treating an entire prompt prefix as the organization.
- Current smoke output distinguishes same task type/different subject
  (`donor report`) from same topic/different task (`wetlands`) and leaves the
  incognito fixture without extracted fields.
- Added field-vector storage through the shared `VectorStore` abstraction using
  the `workstream_field_vectors` table in `memory.db`.
- Added a deterministic semantic embedding probe to the Slice 1 harness. The
  riparian/watershed query has no exact topic match, but vector-backed topic
  search returns wetlands-related workstreams with reasons such as
  `semantic_topic_similarity`.
- The semantic probe initially pulled in a forest donor report via broad
  semantic type similarity. The experiment now scopes the riparian/watershed
  comparison to topic fields, which is a useful early signal that semantic
  matching should be field-policy aware rather than one global score.

Risks:

- A dedicated `memory.db` avoids expanding `chat_sessions.db`, but it creates a
  new system DB to document and maintain.

## Slice 2: Refactor `memory_ops` For Workstream Operations

Goal: replace the current narrow conversation-history `memory_ops` behavior with
the workstream operation surface backed by Slice 1 persistence. Conversation
history is not part of this tool contract.

Operations:

- `current_workstream`
- `create_workstream`
- `get_workstream`
- `search_workstreams`
- `related_workstreams`
- `workstream_artifacts`
- `link_session`
- `relink_session`
- `unlink_session`
- `update_workstream`
- `record_feedback`

Contract:

- Return JSON text, matching current `memory_ops` behavior.
- Include stable `status`, `operation`, and `workstream_id` fields in metadata-like
  payloads.
- `current_workstream` is read-only and returns an unlinked status when no workstream
  is attached to the session.
- Write operations must record source and confidence.
- User-confirmed writes require explicit `source="user_confirmed"` or an
  equivalent operation argument.

Policy:

- Reads are safe for context scripts and chat if the tool is enabled.
- Writes are allowed but auditable. Later UI/policy can restrict chat-visible
  writes if needed.
- Cross-vault operations are rejected.

Validation:

- Direct Python service tests for each operation.
- Tool-level test for JSON result shape.
- Conversation-history retrieval remains available to context assembly through
  `retrieve_history(...)`, not through `memory_ops`.

Experiment:

- Write one throwaway authoring-style script that uses only `memory_ops`
  operations to create, link, update, and inspect a workstream.
- Evaluate whether the operation names and payloads feel composable enough for a
  real context script.
- Revise the operation surface before registering it broadly.

Risks:

- Existing docs said `memory_ops` was for conversation history. This slice
  changes its scope; docs and tool description must be updated in the same
  commit.

Progress notes:

- Refactored `core/tools/memory_ops.py` into the workstream operation surface
  and removed legacy chat-history operations.
- Added operations for current workstream lookup, workstream create/get/search,
  exact related candidates, artifacts, session link/relink/unlink, field update,
  and relationship feedback.
- Kept the tool return contract as pretty JSON text with stable `status` and
  `operation` fields for workstream operations.
- Added `validation/scenarios/experiments/memory_ops_workstream_probe.py` to drive
  the tool directly against the Slice 1 synthetic fixture without registering it
  in global settings.
- Updated `docs/tools/memory_ops.md` to describe the expanded contract.
- Recorded the product decision that memory exposed to agents is mediated
  through workstreams. Chat history can later feed memory through transcript
  export or extraction, but it is not directly queryable through `memory_ops`.

## Slice 3: Register `memory_ops` For Authoring And Optional Chat Use

Goal: add the refactored memory tool back into settings once its real contract
exists.

Changes:

- Add `memory_ops` to `core/settings/settings.template.yaml` tools with
  `chat_visible: true` so it can be selected and tested from chat.
- Add `memory_ops` to default chat tools during this experimental branch so the
  UI exposes it without manual settings edits.
- Ensure settings reload / tool config surfaces handle the tool.
- Update `docs/tools/memory_ops.md` to clarify that it is callable from authored
  scripts and chat through the normal configured tool path.
- Update architecture docs to record that `memory_ops` is the memory operation
  surface for both chat and authoring.

Validation:

- Unit or integration check that `resolve_tool_binding(["memory_ops"], ...)`
  returns a callable tool spec.
- Monty compile/run smoke where an authoring script calls
  `await memory_ops(operation="current_workstream")`.
- Separate Monty run that creates/links a workstream through `memory_ops`.
- Chat-agent tool call can relink or update the current workstream when
  `memory_ops` is chat-visible in test settings.

Experiment:

- Build two tiny context scripts:
  - memory-on: reads current workstream and links when explicitly told to
  - memory-off/incognito: never writes memory state
- Confirm the difference is transparent from logs/results and does not require a
  hidden platform mode.

Risks:

- Existing user settings may not include `memory_ops`. Reload/repair behavior
  should be checked so default context scripts do not fail unexpectedly.

Progress notes:

- Registered `memory_ops` in the settings template and added it to default chat
  tools so it is available for manual chat experiments.
- Kept `memory_ops` on the normal configured tool path rather than adding a
  separate helper API.
- Added `validation/scenarios/integration/core/memory_ops_chat_tool.py` to prove
  a selected chat agent can call `memory_ops` to link the active session and
  update a workstream.
- Updated chat metadata validation to expect `memory_ops` in the exposed tool
  list.
- Fixed runtime bootstrap to clear the typed settings cache after bootstrap
  roots are established, so settings-backed tools are read from the active
  system root.

## Slice 4: Context-Controlled Workstream Linking

Goal: let context policy decide whether and when a session attaches to a work
workstream.

Integration points:

- Shared chat preflight in `_prepare_chat_execution(...)` has session id, vault,
  prompt, context template, model/tools, and prior persisted history.
- Accepted user request is persisted later inside streaming/non-streaming
  execution. The platform should make session/vault/latest-message context
  available to `memory_ops`, but it should not create or link a workstream as an
  unconditional preflight side effect.
- Context assembly runs before the chat agent answers and is the right place for
  the default memory policy to inspect early signals and choose whether to link.

Recommended approach:

- Do not add `memory_service.ensure_workstream_for_session(...)` to chat preflight.
- Ensure `memory_ops` can resolve the active vault and session from the current
  tool/runtime context.
- Update the default context template to run an initial memory policy:
  - call `memory_ops(operation="current_workstream")`
  - if already linked, retrieve current workstream state
  - if unlinked, inspect session title, latest prompt, prior history, and
    working set
  - either create/link a low-confidence new workstream, suggest likely
    continuations, or leave the session unlinked
- Represent incognito/no-memory behavior as a context policy that never calls
  memory write operations. A later UI toggle can select that policy or pass an
  explicit memory mode into context assembly.
- Store initial prompt/session title as low-confidence metadata/fields only when
  a policy chooses to create or link a workstream.

Validation:

- Non-streaming and streaming first chats can remain unlinked when the selected
  context policy does not call memory write operations.
- Default context policy can create and link one workstream when confidence/threshold
  conditions are met.
- Reusing a linked session does not create duplicate workstreams.
- Switching vaults starts a different session and cannot reuse the prior vault's
  workstream.
- Incognito/no-memory context policy leaves no workstream link and writes no workstream
  fields/artifacts.
- Cancellation preserves any explicit link made during context assembly but does
  not fabricate assistant output artifacts.

Experiment:

- Run the initial scenario set with the default policy and inspect which chats
  link, stay unlinked, or suggest continuations.
- Pay special attention to quick retrieval sessions and subject-mismatched donor
  reports.
- Adjust thresholds/policy before adding more signal capture.

Risks:

- If linking happens inside context assembly, a failed context script can leave
  the session unlinked. That is acceptable and should fail closed.
- Context scripts must be careful not to create noisy low-value workstreams too
  early. Thresholds belong in the default policy, not in hidden preflight code.

## Slice 5: Capture Basic Workstream Signals

Goal: populate useful low-risk fields for linked workstreams without LLM
extraction.

Signals:

- session title -> workstream title candidate
- prompt text -> objective candidate if short enough, source `inferred`
- chat turn count from stored messages
- modified/output files from `task_file_mutations` where task scope is
  `chat_session:<session_id>`
- tools selected for the run
- context template used

Implementation:

- Add post-turn update hook after successful chat persistence in both streaming
  and non-streaming paths.
- If the session is unlinked, skip workstream signal capture.
- Query `task_file_mutations` for chat session scope to link modified/output
  artifacts.
- Recalculate simple weight from turns, files modified, outputs, and title.
- Keep extraction deterministic in this slice.

Validation:

- A chat that writes a file links that file as `file_modified` or
  `output_created` when the session is linked.
- An unlinked or incognito chat writes no workstream artifacts.
- A chat with no file activity still updates turn-count signals.
- Repeated turns update `last_seen_at` and weight.
- Failed/cancelled turns do not overstate outputs.

Experiment:

- Review captured workstream state after several realistic chats.
- Check whether the workstream rollups tell the user something they would not
  already know from the chat title and file list.
- Decide whether additional instrumentation, such as read/retrieval tracking, is
  required before related search can be useful.

Risks:

- Vault-state mutation rows may be created after tool execution but before final
  chat persistence; post-turn hook should see them, but ordering should be
  validated.

## Slice 6: Manual Relink And Field Update Through Chat

Goal: make the flexible session-to-workstream link usable.

Behavior:

- User can tell the chat agent:
  - "This is part of the wetlands proposal workstream."
  - "Start a new workstream for this."
  - "Do not remember this session."
  - "Add Foundation X as the organization."
  - "This is not related to the prior donor report."
- Chat agent uses `memory_ops` to relink/update/record feedback when the tool is
  available.

UI:

- No full management UI in this slice.
- Optional minimal chat-visible confirmation text from agent is enough.

Validation:

- `memory_ops(relink_session)` moves the current session from workstream A to B.
- `memory_ops(unlink_session)` removes the current session link and prevents
  later post-turn signal capture unless it is linked again.
- Rejected relation is recorded and suppresses the same candidate for the same
  current workstream.
- User-confirmed organization/topic outranks inferred values in related search.

Experiment:

- Use natural chat instructions to correct memory state in the scenario set.
- Compare the tool calls/results with what a user would expect from phrases like
  "this is not related" or "do not remember this."
- If the agent needs too much prompting to do the right thing, adjust tool
  descriptions and default context instructions before adding retrieval ranking.

Risks:

- If `memory_ops` is not chat-visible by default, validation must enable it in
  test settings.

## Slice 7: Related Workstream Retrieval

Goal: retrieve candidate prior workstreams by transparent relationship type.

Matching v1:

- same organization/person/project exact normalized match
- same topic/type lexical normalized match
- same modified/output artifact path
- same folder namespace from artifact paths
- recent active workstreams in same vault
- feedback suppression for rejected candidates

Result shape:

- candidate workstream id/title
- relation types
- reasons
- confidence
- candidate artifacts
- whether it is safe to auto-include or should be suggested

Ranking:

- relation strength
- workstream weight
- recency decay
- user-confirmed fields
- reuse/continuation count
- feedback penalties

Validation:

- Same organization + same type ranks above same topic only.
- Same topic but different type is returned as related, not continuation.
- Low-weight one-off workstreams are searchable but not high-priority suggestions.
- Rejected candidates are suppressed.
- Cross-vault candidates are never returned.

Experiment:

- Create paired scenario workstreams:
  - same task type, different subject
  - different task type, same subject
  - same organization, different goal
  - one-off retrieval note
- Inspect returned reasons and ranking with a human eye. Do not move to default
  context inclusion until the explanations are clear enough to trust.

Risks:

- Avoid embeddings in this slice. Keep matching explainable and deterministic.

## Slice 8: Related Memory-Aware Context Assembly

Goal: after related-workstream retrieval exists, extend the default memory policy
so default chat behavior can use or suggest prior work without requiring custom
scripts.

Approach:

- Extend the default context template under
  `core/authoring/seed_templates/context/default.md`.
- It should already call `memory_ops(operation="current_workstream")` from Slice 4.
  Add calls such as
  `memory_ops(operation="related_workstreams", ...)`.
- Conservative policy:
  - include current workstream summary/status if compact and high-confidence
  - do not automatically include loosely related source files
  - emit a short system/context note with suggested related work and reasons
  - leave actual file inclusion to explicit user/agent follow-up in v1

Validation:

- Default context script compiles and runs when `memory_ops` is registered.
- Related workstream suggestions appear in assembled context with reasons.
- When no related workstreams exist, default behavior remains close to current
  context assembly.
- Context history protocol safety remains intact.

Experiment:

- Compare the same chat prompts with memory-aware default context and
  incognito/no-memory context.
- Assess whether memory suggestions help the agent answer or merely add noise.
- Record examples where memory should suggest files, suggest a workstream only, or
  stay silent.

Risks:

- Direct tools are all configured tools in Monty. If `memory_ops` is absent from
  user settings, the default context script must handle that gracefully or the
  settings repair path must ensure availability.

## Slice 9: API/UI Inspection Surface

Goal: provide basic visibility into current workstream state and related
suggestions.

API:

- `GET /api/chat/sessions/{session_id}/workstream`
- `GET /api/memory/workstreams/{workstream_id}`
- `GET /api/memory/workstreams/{workstream_id}/related`
- `PATCH /api/memory/workstreams/{workstream_id}`
- `POST /api/chat/sessions/{session_id}/workstream-link`
- `DELETE /api/chat/sessions/{session_id}/workstream-link`

UI v1:

- Show current workstream title/status near session title or in chat settings.
- Show an unlinked/incognito state when no workstream is attached.
- Show a small related-work suggestion panel/message when candidates exist.
- Allow "use", "ignore", "not related", and "unlink" for suggestions if
  feasible.

Validation:

- API response models serialize stable workstream shapes.
- UI can show current workstream without blocking chat.
- User feedback updates memory state.

Experiment:

- Use the UI against scenario sessions and check whether the memory state is
  understandable without reading implementation docs.
- Verify that "unlinked", "linked", and "suggested related work" are visually
  distinct enough.
- Keep or cut UI affordances based on whether they help users correct memory
  behavior.

Risks:

- Keep UI small. Do not build a full workstream manager in v1.

## Slice 10: LLM-Assisted Workstream Extraction

Goal: add model judgment only after deterministic workstream plumbing works.

Approach:

- Use `delegate` or a dedicated internal extraction path to suggest fields from
  recent session history.
- Run after response completion or on idle/session close, not before the agent
  answers.
- Extract:
  - type
  - topics
  - people
  - organizations
  - objectives
  - strategies
  - open questions
- Store all model-derived fields as `source="inferred"` with confidence.
- Do not overwrite user-confirmed fields without explicit user confirmation.

Validation:

- Extraction output is schema-validated.
- User-confirmed fields survive later inferred updates.
- Bad/empty extraction does not break chat completion.
- Validation fixtures cover donor report vs wetlands proposal relationship
  nuance.

Experiment:

- Run extraction offline against saved scenario transcripts before enabling it in
  normal chat flow.
- Compare inferred fields with user-confirmed ground truth.
- Only promote extraction into default behavior if it improves related workstream
  retrieval without creating authoritative-looking false memory.

Risks:

- This is where "magic" can become overconfident. Keep it asynchronous,
  auditable, and low authority.

## Deferred Work

- Embeddings over workstream summaries/topics/objectives.
- Full vault semantic retrieval.
- Read/retrieval instrumentation for all tools.
- Markdown mirrors or editable workstream notes.
- Full workstream management UI.
- Cross-vault memory.
- Graph/centrality maps.
- Automatic promotion of inferred decisions to instruction-grade memory.

## Documentation Updates

As slices land, update:

- `docs/architecture/memory.md`
- `docs/architecture/settings-secrets.md`
- `docs/architecture/chat-sessions.md`
- `docs/architecture/authoring-engine.md`
- `docs/tools/memory_ops.md`
- `docs/use/authoring.md`
- README memory section once user-facing behavior exists

## Next Concrete Step

Continue with Slice 4 in feature development:

1. Build a narrow context-controlled linking experiment.
2. Let context policy inspect the current workstream and decide whether to leave
   the session unlinked, create/link a new workstream, or suggest likely related
   workstreams.
3. Keep incognito/no-memory behavior as a context policy that does not call
   memory write operations.
