# Authoring Feature Parity

## Purpose

This document tracks feature parity between the older authored automation surfaces described in [reference.md](/app/docs/use/reference.md) and the current constrained-Python authoring contract under `core/authoring`.

It is not a promise of one-to-one migration.

Some older features should map directly into the new authoring runtime.
Some should be intentionally dropped.
Some should be replaced by more explicit Python orchestration rather than recreated as framework magic.

## Scope

This tracker is about authored automation behavior:

- scheduled workflows
- context-template-adjacent automation behavior that may later converge into the same architecture
- shared source/sink/tool/model semantics

## Status Legend

- `done`: available now in the constrained-Python authoring path
- `partial`: partly available, but missing limits, safety, or adjacent runtime support
- `planned`: intended to exist in the new model, but not implemented yet
- `rethink`: do not recreate literally; redesign around explicit Python composition
- `drop`: not part of the target architecture

## Current Authoring Surface

Current authored constrained-Python workflows support:

- markdown artifact with frontmatter plus one fenced `python` block
- `workflow_engine: monty` during transition
- canonical top-level `authoring.*` manifest keys
- `retrieve(...)`
- `generate(...)`
- `output(...)`
- `call_tool(...)`
- typed attribute-access results
- host-provided `date.*()` helpers
- compile-only contract inspection and draft validation

Still missing from the intended surface:

- `import_content(...)`
- unified context-template execution on the same runtime

## Frontmatter Parity

### Authoring Scope Manifest

- old surface: mixed directives and workflow-level metadata
- target status: `done`
- new shape:
  - `authoring.capabilities`
  - `authoring.read_paths`
  - `authoring.write_paths`
  - `authoring.tools`
- notes:
  - this is now the canonical authored shape
  - file reads, file writes, and tool calls fail closed unless explicitly declared
  - nested `authoring:` objects and unprefixed fallback keys are no longer the supported authored contract

### `workflow_engine`

- old surface: required engine selector
- target status: `rethink`
- notes:
  - currently still needed as `workflow_engine: monty`
  - long-term direction is to de-emphasize workflow engines as an architectural concept
  - eventual target is one automation architecture, not multiple peer engines

### `schedule`

- old surface: cron / once scheduling
- target status: `done`
- notes:
  - already validated and used by the current constrained-Python workflow path
  - compile/load parity matters here

### `enabled`

- old surface: toggle scheduled execution
- target status: `done`
- notes:
  - unchanged conceptually

### `week_start_day`

- old surface: shared date-pattern behavior
- target status: `done`
- notes:
  - still important for date token semantics and shared runtime behavior

### `passthrough_runs`

- old surface: context-template-specific
- target status: `planned`
- notes:
  - likely belongs in the converged automation/context architecture
  - not yet part of the constrained-Python workflow path

### `token_threshold`

- old surface: context-manager gating
- target status: `planned`
- notes:
  - likely survives only if context automation converges into the same runtime

## Directive / Capability Parity

### `@input`

- old surface: directive-based file / variable reads with selectors and routing
- target status: `partial`
- new shape:
  - `await retrieve(type="file", ref=..., options=...)`
- direct parity already present:
  - file reads
  - glob/selector behavior via shared runtime
  - `required`
  - `refs_only`
  - `pending`
  - `latest`
  - `limit`
  - `order`
  - `dir`
  - `dt_pattern`
  - `dt_format`
- missing / changed:
  - variable/buffer reads are not part of the new contract and should likely be re-expressed through `state` rather than legacy buffer terminology
  - direct input-side routing (`output=...`, `write_mode=...`, `scope=...`) should be treated as `rethink`
  - `images`, `head`, `tail`, and `properties` need explicit evaluation for the new contract rather than assumed carry-over
- notes:
  - the new model is better at prompt placement because retrieved content is inserted explicitly in Python
  - file access policy itself is now `done` through `authoring.read_paths`; the remaining `partial` status is about non-file surfaces and old routing-era options

### `@output`

- old surface: route step output to file / variable / context
- target status: `partial`
- new shape:
  - `await output(type="file", ref=..., data=..., options=...)`
- direct parity already present:
  - file output
  - `mode=append|replace|new`
- missing / changed:
  - variable/buffer output should be treated as `planned` through a future `state` model, not recreated as legacy buffer routing
  - context output is `planned`
- notes:
  - file write policy itself is now `done` through `authoring.write_paths`

### `@header`

- old surface: prepend heading on file output
- target status: `drop`
- new shape:
  - compose header text explicitly in Python before calling `output(...)`
- notes:
  - the old DSL needed this because file composition lived in framework directives
  - the constrained-Python authoring surface should not expose it as a first-class option

### `@model`

- old surface: step model selection, including `none`
- target status: `partial`
- new shape:
  - `generate(prompt=..., instructions=..., model=..., options=...)`
- direct parity already present:
  - explicit model choice
- missing / changed:
  - `none` does not translate literally because the new model expresses non-LLM behavior by simply not calling `generate(...)`
  - this is a `rethink`, not a missing feature
  - `thinking` currently exists in a narrow form

### `@write_mode`

- old surface: append / replace / new
- target status: `done`
- new shape:
  - `output(..., options={"mode": ...})`

### `@run_on`

- old surface: per-step weekday gating
- target status: `rethink`
- notes:
  - the old meaning assumed step-structured workflow execution
  - the new model is general Python orchestration, so this should likely become either:
    - explicit Python date checks
    - or a future helper/capability if that proves too repetitive
  - do not rush to recreate it as hidden framework behavior

### `@tools`

- old surface: per-step tool enablement with optional routing
- target status: `partial`
- new shape:
  - `await call_tool(name=..., arguments=..., options=...)`
- notes:
  - this should not be recreated as hidden tool-enabled generation by default
  - explicit orchestration is the preferred model
  - implemented now for declared tool names from `authoring.tools`
  - the current MVP returns inline textual results only
  - older output-routing behavior should be reconsidered carefully instead of carried over wholesale

### `@cache`

- old surface: context-template caching
- target status: `planned`
- notes:
  - should be reconsidered only in the converged context/workflow architecture

### `@recent_runs`

- old surface: context-template chat-history access
- target status: `planned`
- notes:
  - likely a future `retrieve(type="run", ...)` or related history/state surface

### `@recent_summaries`

- old surface: context-template summary access
- target status: `planned`
- notes:
  - likely part of future run-history/state retrieval rather than a special directive

## Pattern Parity

### Date Tokens

- old surface: `{today}`, `{tomorrow}`, `{this-week}`, etc.
- target status: `partial`
- new shape:
  - prefer Pythonic `date.today()`, `date.tomorrow()`, `date.this_week()`, etc.
- notes:
  - this is intentionally not literal parity
  - token semantics survive, but the preferred authoring form is now Python method calls

### Path Composition

- old surface: string interpolation and date-pattern substitution
- target status: `rethink`
- notes:
  - prefer explicit Python string/path construction
  - avoid rebuilding a second mini-language when ordinary Python is enough

## Buffer / Routing Parity

### Buffers / Variables

- old surface: run/session scoped variable routing
- target status: `rethink`
- notes:
  - “buffer” should not remain the main author-facing concept
  - future design should center on `state`
  - local Python variables already handle most intra-run flow more naturally

### Routing

- old surface: `output=` and related sink routing inside directives
- target status: `rethink`
- notes:
  - the new model is stronger when reads, transformations, and writes are explicit Python steps
  - keep routing only where it remains a genuine host-boundary concern

## Features That Are Probably No Longer Needed

These are not “missing” by default. They may simply be obsolete under the new composition model.

### Forced Prompt Ordering By Framework

- old surface: inputs were injected according to framework behavior
- target status: `drop`
- notes:
  - explicit Python prompt composition is better

### Hidden Cross-Step Framework Plumbing

- old surface: many concepts existed to move data between step-shaped framework stages
- target status: `drop`
- notes:
  - local Python variables handle this directly and more transparently

## Near-Term Priorities

These are the highest-value parity / capability targets for the next phase.

1. strict frontmatter capability enforcement
   - completed for file reads, file writes, and tool calls

2. `state` design
   - replace legacy buffer-thinking with a durable off-context artifact model

3. `import_content(...)`
   - complete the core host-boundary surface

4. context-template convergence
   - decide which context features become first-class in the shared authoring architecture

## Non-Goals

- restoring full parity with the retired `python_steps` experiment
- rebuilding directive-era magic where explicit Python is clearer
- preserving buffer-era concepts as the primary authoring model

## Revisit Criteria

A feature marked `rethink` should only be promoted to concrete implementation if:

- explicit Python composition is clearly too repetitive
- the host boundary still needs a first-class abstraction
- the resulting contract is inspectable and teachable to an LLM
- the feature improves clarity instead of hiding control flow
