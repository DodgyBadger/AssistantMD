# PRD: Memory, Work Workstreams, and Adaptive Context

## Summary

AssistantMD memory helps the agent assemble the right working set for the task
at hand by remembering prior workstreams and the vault material used during
that work.

The vault remains the source of truth. Memory does not replace vault files with a
hidden agent database. Instead, it tracks the shape of work as it happens:
current objective, topics, people, organizations, files used, outputs created,
and prior workstreams that may be relevant. The default context assembly path uses
that memory conservatively to suggest or include useful context, while authored
context scripts remain the override point for users who want explicit control.

## Goals

- Give users useful continuity across chat sessions without requiring them to
  manually write custom context scripts for every project.
- Track every chat session as a new workstream or continuation of an existing
  workstream.
- Use workstreams as the gateway into relevant vault material for similar
  future work.
- Keep memory transparent: show why prior work or files were considered
  relevant.
- Preserve composability: expose the same memory primitives to default context
  assembly and user-authored context scripts.
- Keep generated memory and inferred relationships as candidates, not hidden
  authority.

## Non-Goals

- No hidden always-on summarization of the entire vault.
- No requirement that users adopt a fixed memory folder or wiki structure.
- No semantic-search-first design.
- No automatic promotion of generated summaries or inferred decisions into
  authoritative user guidance.
- No attempt to solve full vault understanding in v1.
- No replacement for context assembly scripts.

## User Problems

### Prior Work Is Hard To Reuse

Users often start a new chat or deliverable and manually search for source
material, prior reports, planning notes, or decisions that already exist
somewhere in the vault.

### Related Work Is Multi-Dimensional

Two workstreams can be related by task type, topic, person, organization, project,
artifact pattern, objective, or strategy. A donor report about wetlands may be
related to another donor report by format, and to a wetlands proposal by topic.
Those relationships should not collapse into one opaque similarity score.

### Context Scripts Are Powerful But Too Manual For Defaults

Users can already author context scripts that load exactly the files and history
they want. Many users still expect the default chat experience to notice relevant
prior work and offer help without requiring up-front scripting.

### Generated Memory Can Become Too Authoritative

If AssistantMD infers a decision, topic, or strategy during chat, that inference
may be useful later, but it should not silently become durable instruction.

## Core Concepts

### Vault

The vault is the durable source of truth. Most vault files are treated as source
material: user notes, project files, imported references, drafts, reports, and
curated memory pages.

### Working Set

A working set is the context the agent needs for the task at hand: relevant
notes, prior history, source files, project summaries, decisions, constraints,
recent changes, examples, or instructions.

### Work Workstream

A workstream records the shape of a piece of work. Every chat session belongs
to one workstream, either by continuing prior work or by starting a new
workstream.

Workstreams can be small or substantial. Ranking and aging determine whether
a workstream should influence future retrieval. A short one-file question may
remain a small workstream. A multi-session report with source files and output
artifacts has stronger concrete activity signals.

### Adaptive Context Assembly

Memory feeds context assembly. Context assembly remains the mechanism that
decides what the chat agent sees.

The default context assembly policy becomes memory-aware: it can infer the
current workstream, find related prior workstreams, include safe continuation
context, and suggest looser related material. User-authored context scripts can
call the same `memory_ops` tool or bypass memory entirely.

## Product Behavior

### Chat Start

When a new chat starts, AssistantMD should:

1. Create a provisional workstream or match the chat to an existing active or
   recent workstream.
2. Treat the selected vault as the hard scope for matching. Within that scope,
   use early signals such as user prompt, session title, active files, recent
   files, and explicit user language.
3. If a clear continuation is found, load a conservative working set
   through default context assembly.
4. If related but ambiguous workstreams are found, present them as
   suggestions rather than silently injecting them.

Example:

```text
This looks related to prior work:
- Foundation X donor report: same organization and deliverable type
- Wetlands proposal: same topic
- 2025 donor update: similar format

I can use the report format, wetlands source notes, or Foundation X relationship
notes.
```

### During Chat

As the user works, AssistantMD should update the current workstream with signals:

- objective or mission
- task type
- topics/themes
- people
- organizations
- projects
- files read or retrieved
- files created or modified
- output artifacts
- decisions, constraints, open questions, strategies

Updates can be incremental, but v1 may choose a simpler session-end or response
completion update path if that is more reliable.

### Future Chat Retrieval

When a future chat resembles prior work, AssistantMD should retrieve related
workstreams by relationship type:

- continuation of the same workstream
- same organization/person/project
- same topic/theme
- same task type
- same output format or artifact pattern
- related source files

The system should rank candidates using relationship strength, recency, reuse,
and concrete activity signals.

### User Control

The user should be able to:

- accept suggested prior context
- reject a suggestion
- continue a prior workstream
- start a new workstream
- rename or retitle the current workstream
- eventually inspect and edit workstream metadata

V1 does not need a full management UI, but the design should not prevent one.

## Workstream Data Model

Recommended v1 fields:

```yaml
workstream_id:
vault_name:
title: compact human-readable label
status: active | paused | completed | archived
created_at:
last_seen_at:

type: kind of work or deliverable, not the subject matter
topic: subject/theme of the work; may be a phrase or sentence
entities: named people, organizations, funders, clients, partners, places
project: project, program, initiative, client engagement, or internal work area
objective: outcome the user is trying to accomplish
strategy: reusable approach, format, style preference, decision, constraint, or tactic

artifacts:
  files_read: []
  files_retrieved: []
  files_modified: []
  outputs_created: []
  planning_notes: []

signals:
  turn_count:
  files_read_count:
  files_modified_count:
  outputs_created_count:
  continuation_count:
  last_reused_at:

candidate_matches:
  - workstream_id:
    matched_fields:
```

Field policy:

- Exact-ish fields: paths, vault, status, and relation types.
- Wildcard fields: entities and project.
- Open/fuzzy fields: topic, objective, strategy, and task type text.
- Workstream fields should summarize the unit of work, not mirror the latest
  user prompt. Leave unknown fields empty rather than inventing specificity.
- Candidate search should expose why a workstream matched rather than attaching
  durable confidence scores to extracted fields.

## Ranking And Aging

Every workstream exists, but not every workstream matters equally.

Ranking signals:

- recency
- turn count and duration
- files read/retrieved
- files modified
- outputs created
- explicit objective
- user-provided title
- user-confirmed fields
- repeated continuation
- reuse by later workstreams
- relationship type to current work

Aging behavior:

- Workstreams decay over time unless reinforced by reuse, continuation, durable
  outputs, user confirmation, or explicit archival/pinning.
- Small one-off workstreams should remain searchable but rarely appear as
  proactive suggestions once ranking policy exists.
- Completed or archived workstreams may still be useful as format references,
  source references, or historical evidence.

## Context Assembly Contract

Memory provides recommendations. Context assembly applies policy.

Default behavior:

- The default context assembly path is memory-aware.
- It can include clear continuation context automatically.
- It should suggest ambiguous candidate workstreams before pulling them into the
  working set.
- It should explain the route: why prior work was considered relevant.

Custom behavior:

- User-authored context scripts can call `memory_ops(...)` directly, the same
  way they call tools such as `file_ops_safe(...)`.
- Users can choose stricter or looser policies.
- Users can ignore inferred workstreams, include only confirmed memory, scope to
  specific project folders, or build specialized working sets.

Candidate `memory_ops` operation surface:

```python
await memory_ops(operation="get_workstream")
await memory_ops(operation="search_workstreams", field_type="topic", value="wetlands", limit=5)
await memory_ops(operation="link_session", workstream_id="...")
await memory_ops(operation="update_workstream", topic="Wetlands donor report for Foundation X")
```

The default memory behavior should be implemented through the same `memory_ops`
operations available to authored context scripts. Whether the chat agent can
call `memory_ops` directly is a configuration and policy choice; the operation
contract should not fork between chat and authoring. If a behavior cannot be
recreated or modified by a context script using `memory_ops`, it is too hidden.

## Persistence And Derived Indexes

Recommended v1 persistence:

- Store workstreams in a system database with direct text fields on each
  workstream row.
- Link workstream records to chat sessions, vault names, file paths, and artifacts.
- Do not require markdown workstream files in v1.
- Keep the door open for future markdown export or user-editable workstream notes.

Derived indexes:

- Direct workstream fields form the first indexing surface.
- Topic, task-type, objective, and strategy vectors are derived from workstream
  fields. Indexing happens when workstreams are created or updated, and non-vector
  field search remains available if embedding is unavailable.
- Entity and artifact indexes are derived from workstream fields/artifacts.
- The system should not first infer a global vault-wide entity/theme map.
  Information enters memory through observed workstreams and their linked vault
  material.

Semantic search:

- Useful later for fuzzy matching over workstream summaries, topics, objectives,
  and strategies.
- Should not be the first authority layer.
- Exact entity/path matching should remain separate from semantic similarity.

## Inputs And Instrumentation

To make workstreams useful, AssistantMD needs to observe more than file
mutations.

Potential inputs:

- chat session id and title
- selected vault
- user prompts and assistant summaries
- retrieved history
- context assembled by context scripts
- files read by tools
- files retrieved by future search/retrieval tools
- files modified through vault mutation routing
- output artifacts created
- workflow runs related to the same work

Open implementation question: v1 may start with chat/session metadata, selected
vault, file mutations, and explicit files included by context assembly, then add
read/retrieval instrumentation as those tools mature.

## Trust And Transparency

AssistantMD should distinguish:

- source vault files
- imported files
- generated summaries
- inferred workstream fields
- user-confirmed workstream fields
- output artifacts
- candidate recommendations

Generated memory starts as evidence. A workstream can suggest that a file,
decision, or strategy was useful before, but should not silently make it
authoritative for new work.

Every recommendation should be explainable:

```text
Suggested because:
- same organization: Foundation X
- same deliverable type: donor report
- prior workstream created output: Reports/Foundation-X/2025-update.md
```

## V1 Scope Recommendation

Build the smallest useful slice:

1. Add workstream persistence.
2. Assign every chat session to a new or existing workstream.
3. Extract/update a small set of fields from chat/session metadata:
   title, type, topics, organizations, objectives, artifacts.
4. Link workstreams to chat sessions and files modified through existing mutation
   routing.
5. Add field-aware workstream search by exact fields and simple lexical matching.
6. Add conservative default context assembly suggestions for candidate workstreams.
7. Expand `memory_ops` so context scripts and chat tools use the same memory
   operation surface.
8. Add enough UI/chat messaging to show suggestions and reasons.

Defer:

- embeddings
- full vault semantic retrieval
- markdown workstream mirrors
- full workstream management UI
- complex graph/centrality maps
- automatic promotion of inferred decisions

## Affected Areas

- `core/memory/`: likely home for workstream service or broker integration.
- `core/chat/`: session-to-workstream assignment and chat metadata links.
- `core/authoring/context_manager.py`: default context assembly integration.
- `core/tools/memory_ops.py`: canonical tool contract for conversation history
  and workstream operations.
- `core/authoring/`: ensure `memory_ops` is available to context scripts through
  the existing direct tool-call surface where policy allows it.
- `core/vault_state/`: artifact links from routed mutations and vault paths.
- `api/models.py` and `api/endpoints.py`: current workstream, workstream search, and
  user action endpoints.
- `static/`: UI affordances for candidate-work suggestions or current workstream
  state.
- `docs/architecture/memory.md`: architecture contract update.

## Validation Targets

Recommended validation scenarios:

- A first chat creates a workstream and links it to the chat session.
- A second chat with matching organization/type retrieves the first workstream as a
  related candidate with reasons.
- A same-topic but different-type chat is related by topic, not continuation.
- A short one-file question creates a small workstream that is searchable but not
  proactively suggested over stronger matches once ranking policy exists.
- User rejection prevents a suggested workstream from being injected again for the
  same current workstream.
- A context script can search for candidate workstreams through `memory_ops(...)`.

## Open Questions

- Should workstream extraction run after every assistant response, on session idle,
  or through a session-end summarization pass?
- What is the minimum UI for accepting/rejecting related context?
- How should users manually merge, split, or reassign workstreams?
- Should workstream state ever be mirrored into markdown by default?
- What is the first safe source for files read/retrieved, not just modified?
- What fields should be user-confirmable in v1?
- How should default context assembly behave when multiple candidate workstreams are
  plausible but none is clearly a continuation?
- If a session creates bad or noisy memory, should the correction path hard-delete
  the workstream, archive it, or suppress it from retrieval/default context?

## Next Phase

Feature development should start by locating the current chat session lifecycle,
context assembly entry points, and persistence patterns, then propose the
smallest workstream persistence and matching slice before adding UI behavior.
