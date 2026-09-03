# Development Documentation Reorganization Plan

## Objective

Reduce architectural documentation drift by replacing the detailed subsystem
library with one concise current-state overview. Group contributor setup,
architecture orientation, and architecture decision records under
`docs/development/`.

Status: complete.

## Target Structure

```text
docs/development/
├── architecture.md
├── dev-setup.md
└── adr/
```

`architecture.md` owns only the system map, major execution/data flows, trust
boundaries, storage ownership, capability categories, and extension seams. Code
owns implementation detail; ADRs own rationale and rejected alternatives;
setup, security, tool, and user guides retain their existing responsibilities.

Move `docs/setup/development.md` to `docs/development/dev-setup.md`. Move every
ADR without changing its filename or content except for links made invalid by
this reorganization. Remove `docs/architecture/` after folding its durable
cross-system information into the new overview.

## Compatibility and Concurrent Work

Update all repository links, agent-guide instructions, ADR evidence references,
and root planning references to the new locations. Preserve the current
uncommitted advanced-shell stdio documentation contract by carrying its
single-user launch-limit and structured-path boundaries into the consolidated
overview before removing the modified subsystem files. Do not touch unrelated
code, configuration, validation, or release-workflow changes in the shared
worktree.

## Validation

- Search tracked text for stale `docs/architecture/`, `docs/adr/`, and
  `docs/setup/development.md` references.
- Verify every relative Markdown link in the moved and changed documentation
  resolves to an existing file or local anchor.
- Confirm `docs/architecture/` and `docs/adr/` contain no remaining files.
- Review the overview against current subsystem directories and accepted ADRs.
- Run whitespace and diff checks. No product validation suite is required for a
  documentation-only relocation.

## Next Phase

Implement the moves and overview, repair references mechanically, then perform
a focused documentation cleanup review before committing only this
reorganization.
