# Memory System Sketch

## Purpose

AssistantMD memory should let a user author durable, inspectable memory behavior
from markdown, workflows, context scripts, and retrieval tools.

The source of truth should remain the vault. Indexes, rankings, embeddings, and
task state are derived services that help select useful vault content. They
should be rebuildable or scoped runtime state, not hidden canonical memory.

This sketch defines the current direction for memory primitives and the
substrate needed to support them.

## Memory Types

Memory has two related forms:

1. Captured memory
   - Facts, decisions, preferences, project state, and session conclusions
     extracted during use.
   - Usually written to curated markdown files.
   - Best produced by chat agents, workflows, or context scripts that summarize
     recent activity into user-readable notes.

2. Vault knowledge
   - Existing vault content selected at the moment a chat, workflow, or context
     script needs it.
   - Includes authored notes, imported artifacts, captured memory files, and
     generated project materials.
   - Best served by retrieval primitives that can scope, rank, and explain why
     files were selected.

These overlap because captured memory becomes vault content. A memory file such
as `memory.md`, `project_memory.md`, or `session_memory.md` is both an output of
captured memory and an input to vault-knowledge retrieval.

## Current Building Blocks

Current app surfaces already support a basic memory system:

- Markdown vault files are durable, editable, and inspectable.
- Chat history is stored in `system/chat_sessions.db`.
- `core/memory/service.py` brokers structured conversation-history retrieval.
- `retrieve_history(...)` and `assemble_context(...)` let context scripts load
  safe conversation units.
- `memory_ops` exposes conversation-history inspection when enabled.
- Workflows and context scripts can read, write, and summarize vault content.
- `pending_files(...)` can select files that changed since a workflow or chat
  scope last completed them, with diff metadata from pending completion
  snapshots.
- Vault state tracks the whole vault through `system/vault_state.db`, scheduled
  scans, manual scans, and AssistantMD mutation routing.

Vault state is the key substrate for vault-knowledge memory. See
`vault_state.md` and `docs/architecture/vault-state.md`.

## Design Principles

- Vault files are canonical.
- Captured memory should be readable and editable as normal markdown.
- Retrieval indexes are derived from vault files and vault-state observations.
- Memory should distinguish evidence from instruction. Agent-generated or
  inferred memory should not silently become durable behavioral guidance.
- Captured memory should carry provenance, scope, review state, and use policy
  when those signals affect future retrieval or context assembly.
- Composability matters more than a single built-in memory policy.
- Context scripts and workflows should be able to compose selectors, diffs,
  retrieval, summarization, and writes.
- Retrieval should return evidence: selected paths, snippets or summaries,
  scores/signals, and enough metadata for debugging.
- Scope should be explicit. Project-specific memory should not accidentally pull
  unrelated vault material unless the author asks for broader scope.
- Start with small, stable primitives. Add customization only where authored
  workflows need it.

## Memory Governance

OB1's strongest reusable idea is not its database shape; AssistantMD should not
make a hidden database the canonical memory store. The useful idea is the trust
model: future agents need to know where a memory came from, what scope it
belongs to, whether a human reviewed it, and whether it may be used as
instruction or only as evidence.

AssistantMD should encode that governance in markdown/frontmatter and derived
index metadata, not as a separate canonical memory table.

Useful governance fields for captured memory files or memory items:

- `memory_type`
  - decision
  - fact
  - preference
  - lesson
  - constraint
  - open_question
  - failure
  - artifact_reference
  - work_log
- `provenance`
  - observed
  - inferred
  - generated
  - user_confirmed
  - imported
  - superseded
  - disputed
- `use_policy`
  - instruction
  - evidence
  - requires_confirmation
  - do_not_auto_inject
- `review_status`
  - pending
  - confirmed
  - evidence_only
  - restricted
  - stale
  - rejected
  - disputed
  - superseded
- `source_refs`
  - vault paths
  - chat session IDs
  - workflow IDs or task IDs
  - imported source URLs or file references
- `scope`
  - vault
  - path namespace
  - project
  - chat session
  - workflow
  - user-authored custom scope
- `confidence`
- `stale_after`

Default policy:

- user-authored or user-confirmed memory may be used as instruction when scoped
  appropriately.
- imported memory may be used as instruction only when imported from a trusted
  source or explicitly marked that way.
- agent-generated, model-inferred, and workflow-summarized memory starts as
  evidence, not instruction.
- stale, disputed, superseded, or rejected memory should not be auto-injected.
- broad vault-wide instruction should require explicit user-authored or
  user-confirmed memory.

This lets context scripts and retrieval tools make conservative choices without
hiding the policy. A context script can choose to include only instruction-grade
memory for behavior shaping, while a research workflow can include evidence-only
memory with citations and warnings.

## Retrieval Signals

Semantic retrieval is useful, but it should not be the only signal.

Likely retrieval signals:

- lexical match over filenames, headings, tags, and content
- semantic similarity from embeddings
- vault graph centrality from links and inferred relationships
- attention from frequent or recent file/folder activity
- recency and change history from vault state
- path and namespace constraints
- frontmatter, tags, and file classification
- workflow-provided relationships or annotations
- captured memory priority, if represented in markdown metadata

PageRank-style graph ranking is best treated as one ranking signal, not a full
memory system. It can help identify central or authoritative notes, especially
inside a project namespace. It should not depend only on wikilinks. The graph can
include explicit links, markdown links, tags, shared folders, frontmatter
relationships, citations, semantic-neighbor edges, and workflow-authored edges.

The graph signal should answer: "Which vault artifacts appear central or
authoritative within this scope?" Semantic retrieval should answer: "Which vault
artifacts appear relevant to this query?" Good retrieval will often combine both.

Attention should be an early derived signal because vault state already captures
the raw material for it. Attention is not the same as importance: an old design
note may be important but quiet, while a daily log may be noisy but only
temporarily relevant. The attention signal should answer: "Which files, folders,
or namespaces are active right now, or have been repeatedly active over time?"

Useful attention measures:

- files changed most often
- files changed recently
- folders with dense recent activity
- namespaces with sustained activity over days or weeks
- files repeatedly selected by pending workflows
- files read, retrieved, or mutated by chat/workflow/tool execution
- recurring headings, tags, or frontmatter terms in recently active files

The first version can be computed from `vault_file_events` and `vault_files`.
Later versions can add read/retrieval activity once those events are explicit.
Attention should feed retrieval ranking and scope suggestions, not decide memory
policy by itself.

## Authoring Primitives

The user-facing memory system should be built from primitives a workflow or
context script can compose.

### Conversation History

Primitive:

- retrieve structured chat/session history
- filter by session, limit, message type, and tool events
- assemble safe history units back into context

Current surface:

- `retrieve_history(...)`
- `assemble_context(...)`
- `memory_ops`

Near-term direction:

- Keep conversation memory behind `core/memory/service.py`.
- Add capture workflows that summarize recent chat into markdown memory files.
- Avoid making chat history itself the long-term memory store.

### Captured Markdown Memory

Primitive:

- write, append, consolidate, and curate markdown memory files
- preserve provenance, scope, source references, review status, and use policy
- keep generated memory compact and source-linked rather than copying raw
  transcripts or large file dumps

Example patterns:

- a context script extracts facts from recent chat into `session_memory.md`
- a nightly workflow merges session notes into `memory.md`
- a project workflow maintains `Projects/Foo/project_memory.md`
- a preference workflow updates `AssistantMD/Memory/preferences.md`

Near-term direction:

- Prefer authored workflows over hidden automatic memory writes.
- Use rollback-protected file mutation APIs for AssistantMD-authored writes.
- Let users inspect and edit captured memory directly.
- Add starter templates that write categorized memory sections such as
  decisions, facts, preferences, lessons, constraints, open questions, failures,
  next steps, and artifact references.
- Treat generated capture as evidence by default unless the user confirms or
  edits it.
- Do not store raw chat transcripts, model reasoning traces, secrets, large code
  blocks, or private dumps as captured memory by default. Store summaries and
  source references.

Possible frontmatter shape:

```yaml
memory_type: decision
provenance: generated
use_policy: evidence
review_status: pending
scope:
  kind: project
  value: Projects/Foo
source_refs:
  - chat_session: abc123
  - path: Projects/Foo/notes.md
confidence: 0.6
stale_after: 2026-08-01
```

The exact schema should stay flexible until a concrete capture workflow needs
strict validation, but retrieval should be able to read common fields when they
are present.

### Pending Changes

Primitive:

- select files changed since this workflow/chat scope last completed them
- inspect diff metadata for those files
- mark processed files complete

Current surface:

- `pending_files(operation="get", items=...)`
- `pending_files(operation="complete", items=...)`

Near-term direction:

- Use pending as the default primitive for incremental memory workflows.
- Keep pending scoped by execution context for now.
- Add future scope selection only when there is a concrete need to share pending
  baselines across workflows or between chat and workflow runs.

Future scope examples:

- workflow scope
- chat-session scope
- named project scope
- vault-global scope

### Vault Knowledge Retrieval

Primitive:

- retrieve relevant vault artifacts for a query or task
- constrain retrieval by path, project, tags, file class, or explicit namespace
- return evidence and ranking metadata
- return governance metadata when available, including provenance, use policy,
  review status, and source references

Current surface:

- no dedicated vault-knowledge retrieval primitive yet
- `file_ops_safe` can list/search/read files
- vault state can identify changed files and current file metadata

Needed surface:

- a retrieval service that consumes vault state and derived indexes
- an LLM-facing retrieval tool
- an authoring helper for context scripts and workflows
- scoped retrieval inputs that an agent or script can know naturally

Possible tool/helper shape:

```python
vault_retrieve(
    query="deployment decision log",
    scope={"paths": ["Projects/Foo/**", "AssistantMD/Memory/**"]},
    limit=8,
    include=["snippets", "scores", "metadata"],
)
```

The exact interface should wait until the first retrieval slice, but the contract
should stay simple: query, scope, limit, and evidence.

Retrieval results should eventually include a compact reason block:

- matched path
- snippet or summary
- lexical/semantic/attention/graph score signals
- freshness and latest vault-state change
- memory governance fields, if present
- why the item was included or excluded from instruction-grade context

### Indexing

Primitive:

- maintain derived indexes over observed vault files
- rebuild or incrementally update from vault-state change events
- expose index health and freshness

Current surface:

- vault-state manifest and change feed
- scheduled vault scans through `vault-state-refresh`
- file classifications and latest-change metadata

Needed surface:

- index consumer cursor over `vault_file_events`
- background index worker as a system scheduler job
- index tables owned by the retrieval subsystem
- derived attention aggregates by file, folder, and namespace
- configuration for enabled indexes and excluded paths
- observability for last indexed sequence, failures, and next run

Indexing should initially be system-maintained rather than fully user-authored.
The composable layer should be retrieval behavior: scopes, selectors, workflows,
and context scripts. Deeper index customization can come later if real workflows
need custom edge builders, custom embeddings, or custom file classifiers.

Attention aggregation is the lowest-complexity first index because it can be
computed directly from vault-state events without embeddings, chunking, or graph
parsing. It should be considered before semantic or PageRank-style indexes.

Governance indexing should be lightweight at first: parse common frontmatter
fields from current vault files and expose them as retrieval metadata. It should
not create a second source of truth.

### Recall Traces

Primitive:

- record retrieval requests and returned evidence for debugging
- optionally record which retrieved items were used or ignored
- connect retrieval traces to chat sessions, workflow runs, context scripts, or
  validation events

OB1 treats recall traces as a core safety/debugging feature. AssistantMD can
adapt that idea without making every retrieval trace canonical memory.

Near-term direction:

- keep traces as system/runtime observability, not vault content
- start with a small trace table or validation-event payload after
  `vault_retrieve` exists
- store query, scope, limit, returned paths, score breakdowns, governance
  decisions, and any reported used/ignored paths
- allow cleanup/retention like other system runtime state

Recall traces should help answer:

- Did retrieval find the right files?
- Did scope accidentally include unrelated material?
- Did ranking prefer noisy recent files over authoritative quiet files?
- Did a context script treat evidence-only memory as instruction?
- Was bad behavior caused by stale memory, poor retrieval, bad summarization, or
  a model choice?

## Role Of Vault State

Vault state should remain neutral infrastructure.

It provides:

- stable vault identity through `vault_id`
- current file manifest
- deleted/current file state
- monotonic change events
- artifact classification
- scheduled whole-vault observation
- immediate observation of AssistantMD-managed mutations
- retained snapshots for rollback and pending diffs

It should not decide:

- what content is memory
- which notes are semantically important
- which project scope applies to a chat
- how retrieved content is summarized into prompt context

Memory and retrieval services should consume vault state rather than adding a
parallel crawler. If an index can be rebuilt from vault files plus vault-state
events, the vault remains the durable truth.

## Near-Term Architecture

The near-term system should have three layers.

### Layer 1: Observation

Owned by vault state.

- Track all vault files.
- Track AssistantMD writes/deletes immediately.
- Pick up external edits through startup, manual, and scheduled scans.
- Expose change events for downstream consumers.

Status: mostly in place for this branch.

### Layer 2: Incremental Processing

Owned by pending, workflows, and snapshot sets.

- Select changed files for a workflow/chat scope.
- Attach diff metadata when a completion baseline exists.
- Capture completion baselines without treating reads as mutations.
- Let authored workflows process only legitimate new content.

Status: in place for the current pending direction.

### Layer 3: Retrieval

Owned by a future retrieval/index subsystem behind memory-facing APIs.

- Build lexical, semantic, and graph indexes from vault files.
- Consume vault-state changes incrementally.
- Use attention aggregates as an early ranking and scope signal.
- Provide scoped retrieval to chat, workflows, and context scripts.
- Return explainable evidence.
- Include governance metadata and policy decisions in retrieval results when
  available.
- Record lightweight recall traces for debugging retrieval behavior.

Status: planned; not yet implemented.

## Implementation Direction

Recommended next slices:

1. Stabilize vault-state change feed access
   - Add a small service API for downstream consumers to read changes since a
     sequence.
   - Keep it artifact-neutral.
   - Validation target: consumer can read created/changed/deleted events across
     a scan and a routed mutation.

2. Define retrieval index ownership
   - Add an architecture doc section for retrieval index tables and scheduler
     job naming.
   - Treat attention aggregation as the likely first derived index because it
     can be built from existing vault-state events.
   - Validation target: index worker records last processed vault-state
     sequence.

3. Add attention aggregates
   - Aggregate file and folder activity from `vault_file_events`.
   - Weight recent changes separately from long-term churn.
   - Keep the output explainable: counts, latest change, and time window.
   - Validation target: changed files and active folders appear in attention
     results with expected counts and timestamps.

4. Add governance metadata parsing
   - Parse common memory frontmatter fields from vault files.
   - Keep parsed governance metadata derived from markdown.
   - Do not require every file to use the schema.
   - Validation target: files with memory governance frontmatter appear in
     retrieval/index metadata with expected policy fields.

5. Add a minimal vault retrieval service
   - Start with lexical/path-scoped retrieval over current vault files.
   - Return paths, snippets, and metadata.
   - Include available governance metadata.
   - Do not add PageRank or embeddings until the interface is useful.
   - Validation target: scoped query returns matching files and excludes
     out-of-scope files.

6. Add authoring and tool adapters
   - Provide one LLM-facing tool and one authoring helper over the same service.
   - Keep the inputs simple: query, scope, limit, include evidence.
   - Validation target: chat/tool contract and context-script helper produce the
     same retrieval result shape.

7. Add recall traces
   - Record query, scope, returned paths, score breakdowns, and governance
     decisions for retrieval calls.
   - Add optional used/ignored reporting only after there is a concrete caller.
   - Validation target: retrieval trace can explain why a path was returned.

8. Add semantic and graph signals
   - Add embeddings as a derived index.
   - Add graph scoring only after explicit link/path/tag relationships are
     represented.
   - Treat PageRank-style centrality as a ranking feature, not a replacement for
     semantic retrieval.
   - Validation target: rankings include score breakdown metadata.

## Open Questions

- What should the default memory namespace be?
- Should AssistantMD ship a conventional `AssistantMD/Memory/` folder?
- Should captured memory workflows be built-in templates or user-authored
  examples?
- What minimal frontmatter schema should starter memory templates use?
- Which memory governance fields should retrieval understand in v1?
- Should generated memory require a pending review marker by default, or is
  evidence-only enough for single-user local use?
- Where should recall traces live, and how long should they be retained?
- What is the first retrieval index that delivers value with the least hidden
  complexity?
- How should chat ask for project scope: explicit user choice, current vault
  context, active workflow, or inferred path?
- When should pending baselines be shareable across scopes?
- What index freshness guarantees should chat expect before using vault
  retrieval?

## Non-Goals For The Next Slice

- No hidden always-on summarization of user chats into memory files.
- No fully customizable indexing pipeline.
- No PageRank-first memory system.
- No replacement of markdown files as the user-visible memory store.
- No broad migration of existing memory/history APIs before a retrieval service
  contract exists.
