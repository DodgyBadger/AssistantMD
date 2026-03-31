# Cleanup Before Merge

## What Matters Now
- Remove temporary scaffolding and session leftovers.
- Align docs, validation, logging, and behavior.
- Look for small inconsistencies that create future maintenance cost.

## Checklist
- Remove temporary debug code, comments, probes, and dead helpers.
- Confirm no secrets or runtime-state artifacts are being committed:
  never commit real API keys, populated `system/secrets.yaml`, or unintended changes under persistent runtime state.
- Make sure docs match the final behavior:
  update user-facing docs, examples, and `docs/architecture/` when feature behavior, subsystem responsibilities, or execution flow changed.
- Draft the next `RELEASE_NOTES.md` entry for the change.
  Keep the entry user-oriented:
  describe what changed for users, operators, or template authors, not internal architecture churn unless it changes how they use or upgrade the system.
  Source it in this order:
  1. the current effort's root-level implementation plan
  2. the linked GitHub issue, if one exists
  3. commit messages for smaller follow-on additions or cleanup
- Re-read changed error messages and logging for clarity.
- Confirm the final handoff explains:
  what changed, what was verified, and what still needs maintainer action.

## Common Mistakes
- Leaving behind session-only helpers or debug instrumentation.
- Updating implementation without updating docs or examples.
- Accidentally committing secrets or local runtime-state artifacts.
- Writing release notes from memory instead of the implementation plan and issue history.
- Forgetting to mention unrun full validation or unresolved risks.

## Phase Exit
The change is ready for maintainer review or merge preparation.
