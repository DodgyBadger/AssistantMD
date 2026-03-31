# Git and Review Workflow

## Commits
- Use short, imperative, focused commit messages; optional scope prefixes are acceptable (for example, `ui: ...`, `ci: ...`).
- Commit subjects should describe the behavior or invariant that changed, not just the file or subsystem touched.
- Prefer messages that help a future reader answer both:
  - what changed
  - why it mattered
- Avoid vague subjects such as `update browser`, `fix workflow`, or `refactor input`.
- Better examples:
  - `Add browser extraction tool`
  - `Move @input pending/latest selection into directive params`
  - `Default scheduled workflows to disabled`
- When the subject alone is not enough, add a short body covering:
  - the problem
  - the behavioral change
  - any migration note or notable risk
- Keep one logical change per commit; do not mix refactors and behavior changes.
- Confirm with the maintainer before creating a commit.

## Session Wrap-Up
- End each major coding session with a brief review pass for duplication risk (DRY) and lint cleanliness.
