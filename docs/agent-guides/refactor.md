# Refactor Pass Playbook

Use this pattern after a feature/fix is working and validated.

## Workflow
1. Ship behavior first: implement the minimum change that satisfies the requirement.
2. Validate behavior: run targeted local checks and request maintainer full validation.
3. Refactor pass: improve structure without changing intended behavior.

## Refactor Goals (Highest Leverage)
- Remove duplicated logic that can drift:
  - parameter schemas
  - normalization/validation paths
  - repeated result/event payload construction
- Extract large mixed-responsibility functions into focused helpers.
- Centralize cross-cutting utilities (frontmatter edits, path checks, parsing).
- Improve error quality:
  - avoid broad catches that hide diagnostics
  - log structured context before returning user-safe errors
  - preserve informative error artifacts instead of collapsing to empty results
- Enforce observability quality for every change:
  - add or update `system/activity.log` events for new paths
  - include decision-boundary logs (not just start/end)
  - ensure failure paths log actionable context, not generic messages
- Keep public contracts stable (API fields, validation events, user-visible semantics).

## Guardrails
- Refactor in small, reviewable commits.
- Do not mix new product behavior with refactor-only changes.
- Preserve validation/event contracts unless explicitly requested.
- If a refactor reveals a real bug, fix it, call it out explicitly, and keep the diff scoped.

## Activity Log Standard (Required)
- Any new feature/fix must include sufficient activity logging to `system/activity.log`.
- At minimum, log:
  - operation start (with identifiers and key inputs)
  - meaningful branch/decision outcomes
  - successful completion (with key outputs/summary counts)
  - failures (with error type, message, and operation context)
- Use stable `tag` and structured `data` fields so logs remain queryable over time.
- Avoid noisy per-line/per-loop spam; log lifecycle milestones and decision boundaries.
- Never swallow exceptions without an activity log entry.

## Agent Checklist
- Identify duplication hot spots with `rg`.
- Extract one utility/helper at a time and rewire call sites.
- Re-run targeted syntax/tests after each refactor chunk.
- Verify logging coverage for changed code paths:
  - trigger at least one success path and one failure/edge path
  - confirm emitted activity entries are specific and useful
- Provide a short “before/after” summary:
  - what was duplicated
  - what was extracted
  - what behavior stayed unchanged
