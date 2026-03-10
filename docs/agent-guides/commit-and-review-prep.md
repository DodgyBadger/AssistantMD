# Commit and Review Prep

## What Matters Now
- Keep one logical change per commit.
- Make the diff easy to understand without rereading the full session.
- Confirm the commit subject describes the behavior or invariant that changed.

## Checklist
- Review the final diff for accidental scope growth.
- Separate refactor-only edits from behavior changes when practical.
- Confirm docs and validation changes match the implementation.
- Write a focused commit message using [Git and Review Workflow](git-and-review.md).
- Note any unrun checks or maintainer-owned validation requests in the handoff.

## Common Mistakes
- Mixing multiple logical changes into one commit.
- Writing commit subjects that describe files instead of behavior.
- Forgetting to mention validation ownership or remaining maintainer actions.
- Skipping a final duplication and cleanliness pass before committing.

## Phase Exit
Move to [Cleanup Before Merge](cleanup-before-merge.md) when the commit shape is set and only merge-readiness checks remain.
