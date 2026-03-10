# Feature Development

## What Matters Now
- Build the smallest correct slice first.
- Stay close to existing patterns unless the codebase is already drifting.
- Keep behavior changes and cleanup work conceptually separate, even if they land in one session.
- Treat observability as part of implementation, not post-work polish.

## Checklist
- Read the current implementation before editing adjacent code.
- Follow [Coding Standards](coding-standards.md) for typing, naming, and logging expectations.
- Place code according to [Project Structure](project-structure.md).
- Prefer narrow, explicit helpers over broad catch-all logic.
- Add or update decision-boundary logging where the changed behavior needs observability.
- Keep temporary probes or scaffolding easy to remove.

## Common Mistakes
- Writing parallel logic paths that will drift.
- Adding validation or routing rules in multiple places without a shared source of truth.
- Hiding real failures behind broad exception handling.
- Letting implementation sprawl before contract coverage exists.

## Phase Exit
Move to [Testing and Validation](testing-and-validation.md) once the behavior exists in some form and needs deterministic proof.
