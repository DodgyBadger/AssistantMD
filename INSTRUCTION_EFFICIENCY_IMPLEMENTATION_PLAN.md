# Instruction Efficiency Implementation Plan

## Objective

Reduce instruction tokens sent on ordinary chat runs without weakening tool
routing, safety, vault usability, or user-authored context. Make implicit
behavior explicit: no fallback soul or playbook is injected when the user has
not created those files.

## Scope

- Remove the generated enabled-tool name/description list because Pydantic AI
  already supplies the authoritative schemas for bound tools.
- Preserve dynamic warnings for tools skipped because of missing secrets or
  invalid configuration.
- Remove the default soul and playbook fallbacks from the bundled default
  context template; load only user-created files.
- Bound explicit `AssistantMD/soul.md` and `AssistantMD/playbook.md` content in
  the same manner as other user-controlled instruction sources.
- Consolidate duplicated vault-path, Markdown/LaTeX, and response-style wording
  in the base chat instructions.
- Keep the inline-edit guidance in the base instructions, but make it concise
  and explicitly conditional with "if enabled" wording.
- Retain the concise skill catalog so automatic skill discovery continues to
  work; do not introduce relevance filtering in this pass.

## Non-goals

- Do not split every tool policy into capability-specific cards.
- Do not change instruction composition or add chat-mode gating in this pass.
- Do not change tool schemas, tool availability, approval behavior, or user
  context precedence.
- Do not change user-created soul, playbook, workspace, or user-note semantics
  beyond explicit size bounds for previously unbounded sources.

## Affected Areas

- `core/constants.py`: base and conditional instruction text.
- `core/tools/utils.py` and tool binding: dynamic warning-only instructions.
- `core/authoring/seed_templates/context/default.md`: explicit-only soul and
  playbook loading plus bounded content.
- Focused unit and scenario contracts covering instruction composition, tool
  binding, and default context assembly.

## Validation

- Measure the static base, inline-edit, advanced-shell, and generated tool
  instruction token counts before and after.
- Run focused instruction, tool-binding, context-assembly, and inline-edit
  tests.
- Run the complete Ruff, Black, and MyPy production quality gate.
- Request maintainer execution of the full scenario validation suite rather
  than running it as an agent.

## Implementation Sequence

1. Remove capability-list generation while retaining unavailable-tool notes.
2. Remove fallback soul/playbook content and add explicit source bounds.
3. Consolidate base instruction wording, including a lean conditional inline-edit rule.
4. Update focused contract coverage and measure the resulting prompt layers.
5. Run targeted checks and the production Python quality gate, then prepare a
   focused commit for review.
