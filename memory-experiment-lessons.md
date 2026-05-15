# Memory Experiment Lessons

This document captures working lessons from the memory/session experiments.
It is not final product documentation. Treat these notes as design evidence for
the next implementation slices.

## Extraction Shape

The two-step extraction performs better than the original single-pass prompt.

Current baseline:

1. Full chat session -> `summary` and `user_intent`
2. `summary` + `user_intent` + session title -> `domain`, `work_product`, and
   `named_entities`

This reduced prompt leakage. In the single-pass version, some sessions produced
`work_product` values such as `memory entry` or `session memory` because the
prompt framed the task as memory extraction. The two-step version and simpler
prompt produced the user's actual deliverables instead.

## Durable Vs Derived Fields

`summary` and `user_intent` look like the durable interpretation of a chat
session.

They are:

- close enough to the source conversation to be human-reviewable;
- useful for understanding what the user was actually doing;
- reusable as the input for later derived indexes.

The other fields are better treated as rebuildable derived fields:

- `domain`
- `work_product`
- `named_entities`
- possible future fields such as `project_area`, `artifact_type`, or
  `activity_type`

This means we can improve classification prompts, add fields, rebuild vectors,
or tune retrieval policy without needing to reinterpret the full transcript each
time.

## Current Field Behavior

`summary`

- Strong as a review surface and as the durable session narrative.
- Too broad/noisy as a primary retrieval field because it blends topic, task,
  chronology, artifacts, and entities.
- Better used for display and downstream classification than direct ranking.

`user_intent`

- Strong as the user's purpose for the session.
- More useful on real AssistantMD data than on broad public chat datasets.
- Should remain part of retrieval, but likely as one signal rather than the only
  signal.

`domain`

- Currently the strongest broad clustering field.
- Works best when concise.
- Still varies in specificity (`wildfire resilience` vs `conservation grant
  reporting` vs `conservation land stewardship`), which is acceptable for
  semantic search but may need normalization later.

`work_product`

- Improved substantially after prompting for a concise generalized category or
  short noun phrase.
- The useful shape is labels like `annual report draft`, `funder email`,
  `knowledge base`, `workflow script`, `grant tracker update`, and
  `pilot project funding proposal`.
- This may eventually split into a more categorical `artifact_type` plus
  concrete artifacts/paths from vault state.

`named_entities`

- Deriving entities from `summary` + `user_intent` intentionally makes the field
  lossy.
- That seems acceptable for memory because the field should capture central
  people, organizations, and places, not every mention.
- Exhaustive mention lookup should remain a full-text/vault-search concern, not
  memory's job.

## Dataset Lessons

The Humanual-Chat dataset was useful as a worst-case noise test because it has
longer conversations spread across unrelated topics. It exposed noisy retrieval
tails and showed that generic public chat data is not representative of an
AssistantMD vault.

The Ashley_NCC production chat sessions are much more useful for this feature
because they include:

- recurring projects and funders;
- durable file outputs;
- repeated entities and places;
- related but distinct reporting, briefing, and planning work;
- real AssistantMD tool/file workflows.

The real-data extraction looked materially better than the public dataset
extraction.

## Retrieval Lessons

Raw single-field search is useful as an inspection primitive, but probably too
low-level for the main agent-facing related-work workflow.

Early compound retrieval suggests:

- `domain` and `work_product` are strong retrieval signals;
- `user_intent` is useful support, especially for distinguishing similar
  products with different purposes;
- `summary` should be downweighted or excluded from ranking for now;
- candidate reports should show per-field reasons and scores.

The current recommended semantic-only related-work policy is conservative:

- `domain`: 0.45
- `work_product`: 0.35
- `user_intent`: 0.20
- `summary`: 0.0
- automatic recommendation: compound score >= 0.70
- possible related work: compound score 0.55-0.70
- hide below 0.55

This keeps the strongest links as automatic recommendations while moving broad
same-vault/same-domain relationships into a lower-confidence band. The
conservative banding is important because this dataset shows many legitimate
but broad conservation/reporting relationships.

A stricter `domain + support` rule was also tested:

- require high `domain` similarity; and
- require high `work_product` or `user_intent` similarity.

That rule improves precision, but it is too brittle as the only path. It drops
plausible relationships such as greenhouse-gas accounting/CBM work to related
wildfire/GHG funding proposal work when the support fields do not cross the
hard threshold.

The next retrieval implementation should preserve per-field contribution
evidence and expose the confidence band (`automatic recommendation` vs
`possible related work`).

This points toward a future related-session operation that runs a tuned
algorithm under the hood, rather than expecting the tool-calling agent to
manually search and merge individual fields.

## Vault State Signals

Semantic fields are only part of the picture. AssistantMD also has vault-state
signals that may be highly useful for memory:

- files read or retrieved;
- files modified or created;
- shared folders or nearby paths;
- repeated use of the same source files;
- outputs that become durable artifacts;
- recency and session continuity.

Real sessions suggest artifact and file context may be as important as semantic
labels. Future related-work retrieval should compare semantic similarity against
vault-state overlap.

## Current Baseline

For now, the best experimental baseline is:

- two-step extraction;
- durable `summary` and `user_intent`;
- derived `domain`, `work_product`, and `named_entities`;
- vectors over `summary`, `domain`, `work_product`, and `user_intent`;
- exact/wildcard search for `named_entities`;
- scenario-local compound retrieval using field-aware scores.

This is good enough to support the next retrieval-policy experiments, but not
yet final enough to freeze as a product contract.
