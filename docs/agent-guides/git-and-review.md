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
- Create local commits at validated logical milestones without waiting for a
  separate maintainer prompt. A request to implement or proceed authorizes
  normal local checkpoint commits for that work; pushing still requires the
  user's explicit request.
- Before starting a distinct experiment, redesign, or cross-cutting follow-up,
  commit the current coherent work if it is in a valid state. This creates a
  safe rollback boundary and prevents later exploratory edits from becoming
  entangled with accepted work.
- Prefer a meaningful checkpoint commit over a broad stash or a vague WIP
  commit. The checkpoint must still describe a coherent behavior or invariant
  and pass the checks appropriate to its risk.
- Stage intentionally. Preserve unrelated user or agent changes, and never use
  a whole-worktree restore, reset, or stash as a substitute for selecting the
  files or hunks that belong to the commit.
- If the current work is not valid enough to commit, keep the experiment narrow
  and record its starting diff before editing overlapping files. Do not present
  the experiment as a durable checkpoint.

## Session Wrap-Up
- End each major coding session with a brief review pass for duplication risk
  (DRY), lint cleanliness, and uncommitted completed work.
- Do not carry a large validated diff into an unrelated next task. Commit it at
  a logical boundary or explain the concrete reason it cannot yet be committed.
