# Memory And Retrieval Roadmap

## Goal

Build a composable memory and retrieval system for AssistantMD that can use
conversation history, vault files, summaries, decisions, semantic indexes, and
graph indexes without turning memory into opaque automatic context injection.

Memory should remain explicit, inspectable, and policy-driven. The stable
interface should be a small set of high-level operations and retrieval profiles;
the implementation underneath can evolve from conversation-history retrieval to
semantic search and graph activation.

## Current Architecture Context

- `system/chat_sessions.db` is the canonical store for provider-native chat
  history and structured chat tool events.
- Markdown transcripts under `AssistantMD/Chat_Sessions/` are export artifacts.
- `core/memory/service.py` is the shared conversation-history broker.
- `core/tools/memory_ops.py` is the LLM-facing adapter for structured
  conversation-history access.
- Context templates and authoring helpers use the memory broker through
  `retrieve_history(...)` and `assemble_context(...)`.

Memory work should extend `core/memory` as the host-owned broker for memory and
retrieval access.

## Relationship To Vault State

Memory should not own vault scanning, hashing, or file-change detection.

`core.vault_state` should provide the neutral artifact substrate:

- vault-relative paths
- artifact classes
- content hashes
- deleted/changed state
- monotonic change sequences
- a cursor-based change feed

The memory/retrieval layer should consume that substrate for indexing and
invalidation. A semantic indexer should ask vault state for "files changed since
sequence N" when refreshing vault-backed records.

This separation keeps responsibilities clear:

- Vault state records artifact facts and task mutations.
- Memory decides which artifacts, summaries, and conversation records are useful
  for a specific context.
- Retrieval indexes are derived and rebuildable from canonical sources.

## Design Principles

- Composable over automatic: memory is loaded intentionally through tools,
  context scripts, workflows, or explicit profiles.
- Inspectable: every memory load should explain what was selected, from which
  source, under which profile or policy.
- Canonical-source aware: indexes should point back to canonical records such as
  chat messages, vault files, summaries, or user-authored notes.
- Small public surface: prefer stable retrieval profiles over ad-hoc query APIs.
- Deterministic maintenance: post-turn/index maintenance should be system-owned
  and auditable, not improvised by the model.
- Rebuildable indexes: semantic and graph indexes should be treated as derived
  state unless explicitly documented otherwise.
- User control: pinned items, explicit template choices, and scoped retrieval
  should override speculative ranking.

## Conceptual Layers

### Canonical Sources

Canonical sources are the records users or system workflows actually own:

- `system/chat_sessions.db` for provider-native chat history and tool events.
- Vault files for user-authored notes, project files, and authoring files.
- System-maintained summaries or compaction records.
- Future explicit memory items such as decisions, preferences, or project notes.

### Artifact State

Vault state tracks observable file facts and changes:

- current manifest
- file versions by hash
- artifact classes
- change-feed cursor
- task mutation and rollback metadata

Memory uses this layer to discover stale or changed vault-backed records.

### Memory Broker

`core/memory` should remain the host-owned access boundary. It should grow from
conversation-history brokerage into a broader memory service with provider
interfaces for:

- conversation history
- conversation tool events
- explicit memory items
- vault-backed document chunks
- summaries and decisions
- retrieval indexes

Lower-level stores can vary, but callers should continue to depend on the
broker and stable result contracts.

### Retrieval Indexes

Retrieval indexes are derived structures optimized for recall and ranking:

- lexical indexes
- vector indexes
- entity indexes
- graph indexes
- usage and activation statistics

These indexes should store source references, hashes, and audit metadata rather
than becoming the canonical record.

### Policy Interface

The user/model-facing surface should stay small. Prefer:

```python
memory_ops.load(profile="project_brief", scope={...})
memory_ops.load(profile="recent_context", scope={...})
memory_ops.load(profile="semantic", query="...", scope={...})
memory_ops.load(profile="active_graph", seeds=[...], scope={...})
memory_ops.save(type="decision", text="...", scope={...})
```

Exact operation names can change, but the principle should hold: profiles encode
policy, and tool responses explain the policy and selected sources.

## Memory Items

Future explicit memory items should carry enough metadata for filtering,
lifecycle, and audit:

- `id`
- `type`: `note`, `decision`, `preference`, `summary`, `task_state`,
  `observation`
- `text`
- `source_type`: `chat`, `file`, `workflow`, `manual`, `system`
- `source_ref`: session id, message id, vault path, task id, or workflow id
- `source_hash` where applicable
- `vault_name`
- `project`
- `tags`
- `entities`
- `created_at`
- `updated_at`
- `last_accessed_at`
- `pinned`
- optional `ttl`
- lifecycle state: `active`, `archived`, `marked_for_review`

Destructive lifecycle changes should be two-step for model-initiated actions:
mark for review first, then deterministic maintenance or user action performs
deletion/archive.

## Retrieval Profiles

Profiles should be stable contracts even if their implementation changes.

Initial useful profiles:

- `session_history`: structured prior conversation history from the existing
  broker.
- `recent_context`: recent summaries, active session context, and recent tool
  events.
- `project_brief`: pinned decisions, active project summary, current preferences,
  and high-priority notes.
- `semantic`: bounded vector search over scoped memory/document chunks.
- `vault_changes`: recently changed vault artifacts from vault state.
- `active_graph`: graph-activated memories seeded from the current query,
  session, entities, task, and vault.

Each response should include:

- profile name
- sources searched
- filters and scope
- selected item count
- token estimate or output size
- brief selection rationale
- source references and hashes when available

## Graph Activation And PageRank

Treating the vault like a network of webpages is a good ranking idea, but it
should be one retrieval/index strategy rather than the entire memory system.

Use a heterogeneous graph, not only markdown links.

Possible node types:

- file
- heading or document chunk
- chat session
- chat summary
- memory item
- entity
- task
- workflow
- decision

Possible edge types:

- markdown link or embed
- file contains entity
- memory mentions entity
- chat produced summary
- task read or mutated file
- workflow processed file
- file supersedes prior hash/version
- items were retrieved together
- items were injected together
- user pinned or selected item
- semantic-neighbor edge
- same folder or artifact class
- temporal co-use

Edge confidence should be explicit:

- Strong: explicit links, tags, pins, task/workflow provenance.
- Medium: shared named entities, direct summary provenance, same workflow run.
- Weak: semantic similarity, same folder, temporal proximity, co-retrieval.

Use Personalized PageRank or a similar spreading-activation algorithm seeded by
current context:

- active vault
- active session
- current query
- mentioned entities
- selected files
- current task or workflow
- semantic top-N candidates

The graph should augment retrieval by finding important adjacent items that
semantic search alone may miss. It should not silently override explicit
profiles, pins, or template choices.

## Low-Wikilink Vaults

The graph approach should not depend on heavy wikilink usage.

If explicit links are sparse, graph activation can still use weaker but useful
edges:

- folder structure
- frontmatter and tags
- headings
- shared entities
- workflow inputs and outputs
- task mutation records
- chat/file provenance
- co-retrieval and co-injection
- temporal locality
- semantic neighbors

In low-link vaults, graph activation should be conservative and secondary:

1. Generate candidates through profile rules and semantic search.
2. Seed graph activation with those candidates and the active context.
3. Expand to nearby high-confidence neighbors.
4. Rerank and return a small audited result set.

## Maintenance

Post-turn and scheduled maintenance should be deterministic:

- update `last_accessed_at` for loaded memories
- record retrieval and injection audit events
- consume vault-state changes for index invalidation
- re-index changed vault artifacts by hash/sequence
- dedupe or compact near-duplicate memories
- expire TTL items
- archive low-utility items only under conservative rules
- update graph edges from explicit links, provenance, and observed co-use

Pinned, safety-critical, and explicit preference memories should be protected
from automated deletion.

## Suggested Implementation Slices

### Slice 1: Current Contract Cleanup

Document the current memory contract around `core/memory`, `memory_ops`,
`retrieve_history(...)`, and canonical chat storage.

Validation target:

- Existing context-manager validation should continue to show protocol-safe
  history retrieval and assembly.

### Slice 2: Memory Result Audit Shape

Extend memory result contracts so tool/helper responses consistently include
source references, scope, filters, profile name where applicable, and selection
rationale.

Validation target:

- Add or extend a scenario asserting `memory_ops` returns auditable metadata for
  conversation history and tool-event retrieval.

### Slice 3: Explicit Memory Items

Add a small explicit memory-item store behind `core/memory`, focused on manual
or model-assisted notes, decisions, preferences, and summaries.

Validation target:

- Save a scoped decision memory.
- Load it through a profile.
- Confirm pinned/protected metadata is preserved.

### Slice 4: Vault-Backed Index Feed

Consume `core.vault_state` change-feed records to create or refresh
vault-backed memory/document chunks.

Validation target:

- Change a markdown file.
- Refresh vault state.
- Run the memory index update from a sequence cursor.
- Assert only changed artifacts are processed.

### Slice 5: Semantic Retrieval Profile

Add an optional vector index over explicit memory items and vault-backed chunks.

Validation target:

- Query a scoped semantic profile.
- Assert source references, hashes, and selection metadata are returned.

### Slice 6: Graph Index

Build a lightweight graph from explicit links, tags/entities, provenance, and
usage signals.

Validation target:

- Given a small fixture vault with sparse links and shared entities, assert graph
  activation returns adjacent relevant items with edge rationale.

### Slice 7: Hybrid Retrieval

Combine profile rules, semantic candidates, pinned items, recent context, and
graph activation into a bounded result set.

Validation target:

- Compare semantic-only and hybrid retrieval on a scenario where an important
  adjacent item is not semantically close to the query.

## Safety And Product Invariants

- Memory indexes do not mutate vault files.
- Memory retrieval never treats derived transcript exports as canonical chat
  history by default.
- Retrieval remains explicit through profiles, templates, tools, or workflows.
- Every loaded memory should be auditable.
- Generated summaries and model-created memories must preserve provenance.
- Destructive lifecycle actions are reviewable and conservative.
- Vault scanning and file-change detection stay in `core.vault_state`.
- Full validation remains maintainer-owned; agents should run targeted local
  checks only.

## Recommended Next Step

Start with the current memory documentation and result contracts:

1. Treat `core/memory` as the broker to extend.
2. Treat `system/chat_sessions.db` as canonical conversation history.
3. Treat `core.vault_state` as the source of vault artifact changes.
4. Add auditable profile-shaped result metadata before adding new retrieval
   algorithms.

Once vault state has a reviewed manifest and change-feed contract, memory can
consume it for vault-backed indexing.
