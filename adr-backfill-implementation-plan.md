# ADR Backfill Implementation Plan

## Scope

Backfill a small, high-signal set of architecture decision records from recovered
root-level branch planning documents. The current architecture documentation in
`docs/architecture/` remains the source of truth for how AssistantMD works now;
the ADRs capture why major durable shapes were chosen.

## Source Material

- Current contract: `docs/architecture/`
- Recovered branch notes: `/tmp/assistantmd-adr-backfill-source/`
- Recovery index: `/tmp/assistantmd-adr-backfill-source/INDEX.md`

## Candidate Decisions

- Runtime context as the process-wide service composition root.
- Python/Monty authoring surface replacing markdown DSL execution.
- SQLite as canonical chat-session storage with markdown transcripts as exports.
- Process-local execution task coordination for visibility and cancellation.
- Vault-state mutation audit, snapshots, and rollback around task-scoped writes.
- Session summaries as derived memory indexes rather than canonical chat history.
- Settings-backed model/tool registry with secret-pointer separation.
- Multimodal image handling through explicit policy gates and ref fallbacks.
- Scenario-based validation as the durable behavioral proof surface.
- Ingestion source importers split from extraction strategies.
- Chat history broker as the shared safe access layer for persisted and
  in-flight history.
- Cache as the shared off-context artifact store for large or temporary
  generated artifacts.
- Workflow governor as the owner of in-process workflow concurrency policy.
- Declared subsystem-owned system databases instead of one implicit shared
  database.

## Output

- Add numbered ADR files for selected decisions only.
- Keep ADR discovery simple: list or grep `docs/adr/` rather than maintaining a
  separate index file.
- Include a short source-evidence note in each ADR, pointing to recovered plans
  and current architecture docs.

## Validation Target

Documentation-only change. Verify links and headings with targeted file reads;
do not run the full validation suite.

## Next Phase

Feature development: create the ADR documentation files and perform a lightweight
documentation review for consistency with `docs/architecture/`.

## Follow-Up Batch

The first ADR batch covered ten high-level decisions. A second batch adds
decisions whose rationale is strongly inferable from current architecture docs
and recovered branch plans: ingestion boundaries, chat-history brokering,
off-context cache artifacts, workflow concurrency lanes, and system database
ownership.
