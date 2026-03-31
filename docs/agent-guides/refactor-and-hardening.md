# Refactor and Hardening

## What Matters Now
- Reduce entropy after correctness is established.
- Centralize logic that would otherwise drift.
- Tighten error paths and observability.
- Keep contracts stable while improving internals.

## Checklist
- Remove duplicated logic that can drift:
  parameter schemas, validation paths, payload construction, routing decisions.
- Extract mixed-responsibility functions into focused helpers.
- Centralize cross-cutting utilities when drift risk is high.
- Improve error quality:
  avoid broad catches, preserve diagnostics, and keep user-facing failures specific.
- Verify logging coverage for changed paths:
  start, decision, success, and failure milestones with structured context.
- Confirm docs and validation still describe the post-refactor behavior.
  This includes `docs/architecture/` when subsystem boundaries, responsibilities, or execution flow changed.
- If the refactor reveals a bug, fix it explicitly and keep the scope clear.

## Guardrails
- Refactor in small, reviewable chunks.
- Do not mix adjacent feature work into the refactor pass.
- Preserve validation and event contracts unless the change explicitly updates them.
- If a refactor reveals a real bug, fix it, call it out, and keep the diff scoped.

## Observability Standard
- Any new feature or fix should leave behind useful activity logging for the changed path.
- At minimum, cover:
  operation start, meaningful decisions, successful completion, and failures.
- Use stable tags and structured fields so logs remain queryable over time.
- Avoid noisy per-loop logging; prefer lifecycle milestones and decision boundaries.
- Never swallow exceptions without preserving actionable diagnostics.

## Common Mistakes
- Expanding the refactor into adjacent feature work.
- Changing public contracts accidentally while cleaning internals.
- Leaving split-brain validation or policy logic in multiple helpers.
- Calling work “done” once scenarios pass without addressing obvious drift risks.

## Reference Docs
- [Coding Standards](coding-standards.md)
- [Git and Review Workflow](git-and-review.md)

## Phase Exit
Move to [Commit and Review Prep](commit-and-review-prep.md) once the remaining changes are packaging and review-readiness work.
