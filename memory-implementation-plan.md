# Memory Implementation Plan

## Current Decision

Memory is session-scoped. The v1 data model should not contain a separate
work/project aggregation object. A user who wants to continue a prior unit of
work can reopen that chat session. A new session can retrieve related prior
sessions as context candidates without merging their summaries or intents into a
shared canonical record.

This keeps the provenance boundary clear and avoids noisy cross-session merge
logic before real usage proves that a higher-level aggregation is needed.

## Current Architecture Read

- `core/chat/chat_store.py` persists canonical chat sessions in
  `system/chat_sessions.db`, keyed by `session_id` and scoped to `vault_name`.
- `core/authoring/context_manager.py` runs selected context templates and can
  call configured tools through Monty.
- `core/authoring/runtime/monty_runner.py` exposes configured tools as direct
  Monty functions, so `memory_ops` is the right shared operation surface for
  chat agents and context scripts.
- `core/memory/service.py` remains the conversation-history broker.
- `core/memory/session_memory.py` owns session-memory persistence and
  field-aware retrieval.
- `core/vector` owns embedding generation and vector storage abstraction.

## Invariants

- The selected vault is a hard scope.
- One `(vault_name, session_id)` has at most one session memory row.
- No session-memory operation creates or links a separate project/work object.
- `memory_ops` is the canonical operation surface for chat agents and authored
  scripts.
- Retrieval is field-aware: compare `domain` to `domain`, `work_product` to
  `work_product`, and `user_intent` to `user_intent`.
- Generated memory is candidate context, not hidden authority.

## Implemented Slice: Shared Vector Plumbing

Implemented earlier:

- `core.vector.VectorService`
- embedding model configuration through existing `models` settings entries
- embedding-only model aliases via `capabilities: ["embedding"]`
- `embedding_space_id` including provider, base URL, model string, and
  dimensions
- `SQLitePythonVectorStore` with plain SQLite rows and Python cosine search
- validation probe using deterministic test embeddings

## Implemented Slice: Session Memory Persistence

Storage:

- `system/memory.db`
- `session_memories`
  - `session_id`
  - `vault_name`
  - `title`
  - `summary`
  - `domain`
  - `work_product`
  - `user_intent`
  - `named_entities`
  - `created_at`
  - `updated_at`
  - `metadata_json`
- `session_memory_artifacts`
  - `session_id`
  - `vault_name`
  - `path`
  - `artifact_role`
  - `created_at`
  - `metadata_json`
- `session_memory_field_vectors`
  - owned through the vector-store abstraction

Store API:

- `upsert_session_memory(...)`
- `get_session_memory(vault_name, session_id)`
- `delete_session_memory(vault_name, session_id)`
- `search_session_memories(...)`
- `search_session_memories_by_field(...)`
- `find_related_sessions(...)`
- `index_session_memory_fields(...)`

## Implemented Slice: `memory_ops`

Tool operations:

- `extract_session_memory`
- `upsert_session_memory`
- `get_session_memory`
- `search_sessions`
- `find_related_sessions`

The active vault and session default from `MemoryContext`. The tool no longer
accepts a separate memory object id because `session_id` is the identity.
`extract_session_memory` is the automatic creation policy; it reads the
persisted transcript, runs two-step extraction, and writes through the same
session-memory storage/indexing path as `upsert_session_memory`.

## Current Extraction Policy

The best live-model result so far is two-step extraction:

1. Full chat transcript -> `summary`, `user_intent`
2. `summary`, `user_intent`, and title -> `domain`, `work_product`,
   `named_entities`

Working guidance:

- `summary` and `user_intent` are durable.
- `domain`, `work_product`, and `named_entities` are retrieval fields that may
  be rebuilt from durable fields later.
- `named_entities` should be limited to people, organizations, and places.

## Current Retrieval Policy Recommendation

Use field-aware semantic retrieval over session memory fields.

Compound score:

```text
score = 0.45 * domain
      + 0.35 * work_product
      + 0.20 * user_intent
```

Bands:

- `>= 0.70`: automatic recommendation
- `0.55-0.70`: possible related work
- `< 0.55`: hide

`summary` should be shown as explanation/evidence, not used in first-pass
ranking. The stricter domain-plus-support policy is useful as a diagnostic but
too brittle as the default.

This policy is implemented as `find_related_sessions`, leaving
`search_sessions` as the lower-level search primitive. The first implementation
searches indexed session memory fields, but the operation name leaves room for
future transcript and linked-artifact search.
The public `find_related_sessions` operation only accepts `session_id` and
`limit`; it loads stored fields from that session and applies the policy.

## Validation Scenarios

Current focused scenarios:

- `validation/scenarios/experiments/vector_embedding_service_probe.py`
- `validation/scenarios/experiments/memory_session_data_model_probe.py`
- `validation/scenarios/experiments/memory_ops_session_probe.py`
- `validation/scenarios/integration/core/memory_ops_chat_tool.py`
- `validation/scenarios/experiments/ashley_ncc_two_step_extraction_probe.py`

The Ashley_NCC scenario writes artifacts for extraction quality, single-field
retrieval probes, and compound retrieval policy probes.

## Next Slices

### Slice A: Stabilize Session Memory Contract

- Run focused validation scenarios.
- Verify delete/purge cleanup removes session memory.
- Confirm no remaining product-facing docs describe project/work aggregation as
  current behavior.

### Slice B: Context Script Experiment

- Build a default memory-aware context script that can:
  - inspect current session memory
  - search related prior sessions
  - surface candidates transparently
- Keep it opt-in while retrieval policy is still being tuned.

### Slice C: Extraction Timing

Decide when `upsert_session_memory` should run by default:

- explicit chat-agent/tool call only
- context script after enough history exists
- session idle or response-completion background task

The current implementation supports the first two without adding background
automation.

### Slice D: Retrieval Policy Hardening

- Add deterministic tests for compound scoring once the policy moves from
  scenario code into core/product behavior.
- Keep field contribution output in responses so ranking remains inspectable.
- Revisit named-entity exact matching after real data accumulates.
- Keep lexical retrieval simple for now: no custom stopword or domain-filtering
  layer. Tune the existing BM25/vector weights first, and only add filtering
  after repeated retrieval failures point to a specific need.

### Slice E: Vault-State Retrieval Signals

Discuss and design how vault-state should influence `find_related_sessions`.
Candidate signals include:

- shared files read, retrieved, modified, or created;
- shared directories or nearby paths;
- repeated output locations or artifact roles;
- recency of AssistantMD-routed file mutations;
- whether a candidate session touched durable files that still exist.

This should start as an experiment, not an immediate production scoring rule.
The first question is whether vault-state overlap improves recommendations
enough to justify mixing it with semantic field scores.

### Slice F: Memory Pruning And Expiry

Define how session memories should age, decay, or be removed. The design should
distinguish:

- deleting memory when its source chat session is deleted;
- hiding old or low-value memories from default recommendations;
- keeping old memories searchable through explicit `search_sessions`;
- pruning generated vectors or stale derived fields when extraction policy
  changes;
- whether expiry should be time-based, activity-based, user-controlled, or a
  combination.

### Slice G: Shipped Workflow Templates

Use system Authoring files as shipped templates and vault Authoring files as the
active user-owned workflow surface.

- Stop overwriting existing system Authoring templates during startup.
- Add a manual System/Misc action that refreshes packaged system Authoring
  templates when the user explicitly asks for it.
- Add the nightly memory extraction workflow as a disabled packaged system
  template.
- Add Dashboard/Workflows affordances to copy a system template into the
  selected vault.
- Add a workflow enabled/disabled toggle that edits the same frontmatter field
  for every active vault workflow.

## Open Questions

- Should session memory be generated automatically at session idle, or only by a
  selected memory-aware context policy?
- Should memory rows be visible in the UI next to chat sessions?
- Should a deleted chat transcript export also delete any memory artifacts, or
  only the session memory row?
- How should vault-state overlap be weighted against semantic similarity in
  `find_related_sessions`?
- What memory aging policy should affect default recommendations without making
  explicit search forget useful old work?
- What minimum real-data volume is enough before revisiting higher-level
  project/work aggregation?
