# Connection State Transaction Implementation Plan

Status: implemented and hardened through repeated independent reviews. Final
reviews report no remaining actionable findings in the reviewed areas.
Maintainer-owned full validation remains pending.

## Hardening review ledger

The first three independent reviews identified the following required corrections:

- Move MCP mutation admission and OAuth invalidation decisions inside the write
  transaction; replace duplicated encrypted OAuth fences with guarded metadata
  revision checks.
- Correct Google default projection, replacement-default deletion races, domain
  error translation, and permanent slug/identity reservations; remove alternate
  metadata mutation paths that bypass composed credential operations.
- Capture MCP authorization revision before token exchange, consume pending
  attempts once, and preserve newer attempts against stale completion/cleanup.
- Acknowledge MCP invalidation marking on the owning event loop; observe deferred
  resource cleanup failures without claiming logging/cleanup is a SQLite commit.
- Preserve absent/existing access stores while locked through full bootstrap and
  connection APIs; permit diagnostic startup with malformed access databases.
- Restore the direct-run native-connection scenario entry point and add actual
  partial-write rollback, process-exit, YAML retirement, and bootstrap evidence.

All corrections above are implemented and independently re-reviewed. Follow-up
reviews also identified and resolved:

- Mixed-version endpoint/credential reads: credential and OAuth storage resolution
  now checks the captured configuration version within a shared read snapshot.
- OAuth cancellation and shutdown: independent task ownership retains superseded
  and draining attempts until completion; shutdown closes admission and drains
  attempt and completion tasks.
- Google stale reads: status/token reads cannot delete newer grants, and token
  saves always guard the captured credential, including standalone domain calls.
- Google disconnect: current metadata/credential lookup, identity rotation, and
  pending/grant deletion share a transaction, including the absent-credential case.
- Committed failures: metadata and OAuth mutations preserve committed state on
  invalidation failure; rendered API errors explicitly prohibit automatic retry
  and direct callers to inspect the saved state.

The initial passing-check report was insufficient: review exposed missing
assertions and obsolete mocks. Their replacements exercise actual partial writes,
process termination, concurrency, and rendered API behavior. No review/fix stage
reset persistent runtime state or ran the maintainer-owned full suite.

### Final verification record

The parent ran the following final focused test set: **25 passed**.

```bash
uv run pytest -q validation/test_mcp_oauth_hardening.py validation/test_mcp_manager_hardening.py validation/test_chat_mcp_lifecycle.py
```

Relevant individual integration scenarios passed through isolated direct runs:
`mcp_mutation_recovery`, `mcp_connection_isolation`, `mcp_oauth_storage`,
`mcp_oauth_coordinator`, `mcp_advanced_shell_stdio_connections`,
`shared_oauth_foundation`, `encrypted_secrets_boundaries`,
`builtin_connection_configuration`, `google_oauth_coordinator`,
`gmail_connection_api`, `gmail_principal_connection`, `locked_access_bootstrap`,
and `legacy_secrets_migration`. Repair/review agents also verified
`system_database_migrations`, `system_startup_migrations`,
`runtime_bootstrap_cleanup`, and `principal_execution_authority`.

Final complete production gate: Ruff passes; Black reports 432 files unchanged;
MyPy reports no issues in 271 source files; `git diff --check` passes. The final
Gmail scenario replaces a removed-helper mock with a real transactional rollback
test. A transient earlier MyPy import finding did not recur on serial reruns;
no checker rules or production imports were weakened.

The independent final reviews covered transactions/material resolution,
Google mutation and disconnect behavior, locked bootstrap/YAML recovery,
MCP OAuth storage/task lifecycle, and committed API failure projection. No
actionable findings remain from those reviews; this is not a substitute for
the maintainer-owned full profile or live provider smoke checks. No commit was
created and no runtime credentials or connection databases were reset.

## Objective and agreed scope

Deliver MCP connections, native Google connections, and encrypted credentials to
`main` with one SQLite transaction boundary. Replace application-level recovery
for partial cross-database commits with ordinary atomic transactions while
preserving authority, encryption, OAuth race protection, and runtime lifecycle
behavior.

The user has explicitly selected the following scope:

- Keep embedded SQLite; introduce no database service, Turso dependency, or remote
  storage requirement.
- Preserve Markdown as canonical user content and leave unrelated system databases
  alone.
- Support the released plaintext `system/secrets.yaml` upgrade into the final
  encrypted store.
- Do not migrate the intermediate encrypted secrets, MCP, or Google connection
  databases from this accumulated development branch. The sole development
  operator will recreate connections and reenter credentials.
- Do not reset runtime data during implementation. Development operators remove
  obsolete intermediate files and reenter credentials explicitly.

Success is a materially simpler connection lifecycle, not merely fewer files.
Do not retain the saga behind a new database filename or replace it with a generic
transaction orchestration framework.

## Starting implementation and cost

- `core/mcp/service.py` coordinated `mcp.db` and `secrets.db` with staged encrypted
  values, a durable mutation journal, pending/deleting lifecycle states, recovery,
  OAuth fence markers, and terminal-effect dispatch.
- `core/connections/service.py` owned Google metadata in `connections.db`.
  `core/integrations/google/connection.py` independently changes encrypted state,
  applies credential generations, and reconciles deletion records. API services
  coordinate some metadata changes with credential cleanup.
- `core/secrets/service.py` opened and committed its own connections. Its original
  methods cannot simply be called from inside a metadata transaction and assumed
  to participate in that transaction.
- `core/oauth/storage.py` and `core/mcp/oauth_storage.py` supplied guarded encrypted
  persistence for adapters whose external requests can outlive configuration.
- `core/system_migrations.py` registered the three stores separately. Bootstrap
  checks secret readiness before managed migrations and YAML import.
- The YAML importer also spans a SQLite commit and a filesystem rename. That
  genuine cross-resource boundary remains and still needs restart-safe handling.

Relevant decisions: ADR 0015 (subsystem database ownership), ADR 0028 (execution
principals), ADRs 0034–0038 (secrets and connection identity), ADR 0040 (MCP saga),
ADR 0041 (Google generations), and ADR 0045 (application-mediated OAuth).

## Target architecture

### One physical store, separate domain ownership

Use `system/access.db` as the final physical store for:

| State | Domain owner |
| --- | --- |
| Encrypted static credentials, tokens, pending OAuth state | `core/secrets/`, with provider adapters owning payload semantics |
| YAML import progress and imported item identities | `core/secrets/legacy_migration.py` |
| MCP metadata, immutable slug reservations, configuration versions | `core/mcp/` |
| Google metadata, defaults, slug reservations, credential generations | `core/connections/` and `core/integrations/google/` |

The name describes operational access state; it is not a new source of execution
authority. Keep encrypted record identities and authenticated encryption intact.
Do not put credentials into metadata tables or expose secret SQL to API/tool code.

Add a small `core/access_store/` package for connection configuration, transaction
ownership, and the coordinated schema entry point. It must contain no Gmail/MCP
business policy. Domain schema builders remain explicit and operate on a supplied
connection without opening or committing another one.

Register one physical migration target and one ordered migration sequence for
`access.db`. The initial schema contains the final tables directly; do not replay
unreleased saga, singleton Google, or intermediate transport schema history.
Keep existing released migration histories for unrelated databases unchanged.
Migration status, backup, and integrity checks must treat the shared file once.

### Explicit transaction participation

Provide a short-lived internal transaction context with a single SQLite
connection. The outer owner begins, commits, rolls back, and closes it. Nested
domain operations use transaction-bound helpers and never commit, close, or open
an independent write connection. Do not use ambient globals or task-local mutable
transactions; do not permit a transaction to escape its context.

Keep ordinary domain methods convenient: standalone mutations own a transaction;
composed operations use narrowly scoped internal helpers bound to the caller's
transaction. Secret helpers still enforce principal scope, encryption, and guard
checks. The YAML importer retains its explicit system/bootstrap authority path.

Use the project's SQLite configuration consistently, including foreign-key
enforcement, WAL, bounded busy handling, and a documented durability setting.
Acquire write intent before read-modify-write decisions where needed, such as
default selection, generation changes, and OAuth guard comparisons. No network
request, asynchronous wait, subprocess work, or logging sink runs while a write
transaction is held. Avoid accidental nested `with conn` commits under Python
3.13's sqlite3 transaction semantics.

### Atomic connection mutations

MCP create, update, credential replacement/clear, OAuth disconnect, and delete
commit metadata, relevant encrypted changes, and version changes together.
Normalize input before entering the write transaction; recheck current identity
and state within it. Reserve immutable slugs under the same transaction.

Google client-ID changes, secret replacement, disconnect, default changes, and
deletion follow the same pattern. Move metadata/credential orchestration out of
API adapters into domain operations. Deletion and replacement-default selection
are one transaction with encrypted namespace removal and permanent slug
reservation. Preserve UUID non-reuse without retaining a purge-retry journal.

Remove staged secret namespaces, MCP mutation records, pending/deleting states
used solely for partial commits, startup mutation reconciliation, and Google
deletion-purge reconciliation after their replacement assertions pass. Remove
secret copy/relocation/batch helpers only when a caller audit proves they are
unnecessary; legitimate OAuth and YAML migration operations may still need some.

### OAuth races remain a first-class contract

Retain Google credential generation and credential identity bindings. Capture
the relevant credential and source grant before external requests. On completion,
re-read metadata and encrypted guards and persist only if still current, all in
one write transaction. Consume pending attempts atomically with applicable local
state changes. Never hold a transaction during authorization, refresh, discovery,
or account lookup.

For MCP, retain an authoritative OAuth revision/identity on the connection row,
changing it only for OAuth-sensitive mutations. Transaction-bound OAuth storage
checks row existence and this identity in the same transaction as its write.
This replaces the duplicated encrypted cross-database fence marker. Display-only
edits need not invalidate authorization. Adapters issued before disconnect,
credential replacement, or deletion must not recreate pending state or tokens.

Preserve refresh versus reauthorization guards, single-use pending state, expiry,
restart-safe completion, principal isolation, and manual/callback equivalence.
Remove compatibility code for unreleased unbound Google credentials and singleton
connections; retain the released YAML policy that requires OAuth reauthorization.

### Runtime invalidation and failure semantics

Keep retained MCP leases and frozen catalogs. Existing leases may finish against
their captured configuration; new acquisitions must use current committed state.
Do not change this into immediate cancellation of active calls.

Commit the durable mutation before notifying the manager, and acknowledge the
manager's invalidation before returning normal mutation success. The handoff must
be safe from API worker threads and must not run under the SQLite write lock.
Version/existence checks in the manager remain authoritative for new acquisitions,
including cold connections racing with a mutation.

If the process dies after commit, restart reads the committed version and has no
old clients to invalidate. If notification fails in a live process, do not claim
the database rolled back or replay the mutation. Surface a sanitized committed-
but-runtime-unavailable outcome, log the boundary, and keep stale new acquisitions
blocked by authoritative checks. Specify/test the concrete API projection before
coding this path. Do not recreate a durable saga merely to couple logs to commits.

## Upgrade and bootstrap contract

The supported upgrade source is the released YAML file, not any intermediate
development database. Confirm the release baseline against `main` before editing
migration registration.

1. Resolve persistent roots and inspect key configuration and existing encrypted
   records without changing a locked store. Missing, malformed, or incorrect keys
   keep diagnosis available and block execution/secret mutation.
2. With usable key material, initialize or migrate the shared schema. Avoid a
   bootstrap dependency loop between secrets verification and schema creation;
   distinguish an absent fresh store from an existing malformed store.
3. Import eligible YAML secrets and record import identities/fingerprint in one
   SQLite transaction. Retain `local-user` versus explicit `system` ownership and
   the existing exclusion of legacy OAuth pending/token records.
4. Verify imported values before retiring the YAML source to the existing
   `system/migration_backups/secrets.yaml.bak` location. Never overwrite a backup.
5. Retain restart-safe imported/complete phases across the filesystem rename.
   An interrupted rename/completion must not lose secrets or reimport over newer
   values. No plaintext runtime fallback is introduced.
6. Start connection services and the MCP manager only after shared storage and
   applicable YAML import settle. Remove cross-database reconciliation hooks.

While secrets are locked, do not migrate or mutate the shared access file. Adapt
Google metadata/API startup paths so the diagnostic UI still works without
attempting to create missing tables. Unrelated managed database behavior remains
unchanged. Verify fresh, existing-valid, wrong-key, and malformed-store cases.

Development transition is an operator action, not a migration feature: stop the
instance, explicitly archive/reset only `secrets.db`, `mcp.db`, and
`connections.db` and their SQLite sidecars in the configured system root, then
recreate connections and credentials. Preserve vaults, other databases, `.env`,
settings, and shell pairing volumes. Do not execute this reset during automated
validation or planning. Do not silently delete/import obsolete stores at startup;
a small diagnostic for their presence may direct the operator to the reset, but
must not become a compatibility subsystem. Keep this branch-only procedure in
implementation/handoff notes, not permanent product upgrade instructions.

## Validation contracts before implementation

Use deterministic integration scenarios with isolated temporary roots. Extend
assertions before replacing production behavior. Retain the behavioral content
of existing hardening coverage rather than its journal-specific implementation.

| Boundary | Required evidence | Existing targets |
| --- | --- | --- |
| Shared transaction | Inject failure after metadata and after encrypted writes; reopening sees the complete old state, never partial state. Successful commit exposes the complete new state. Include actual process exit before/after commit. | Replace/rename `mcp_mutation_recovery.py` with an atomic connection mutation scenario |
| Identity/defaults | Unique and retired slugs, owner isolation, required replacement default, generation/version increments once per mutation, concurrent default selection | `mcp_connection_isolation.py`, `builtin_connection_configuration.py`, `gmail_principal_connection.py` |
| OAuth races | Late start/completion/refresh cannot revive deleted/disconnected/replaced grants; newer pending state and reauthorization survive stale responses | `google_oauth_coordinator.py`, `mcp_oauth_coordinator.py`, `mcp_oauth_storage.py`, `shared_oauth_foundation.py` |
| Runtime | Warm/cold clients racing with commit, delayed/failed invalidation, active lease completion, new lease rejection, cancellation/shutdown cleanup | `test_mcp_manager_hardening.py`, `test_chat_mcp_lifecycle.py` |
| Encryption | Owner/name-bound ciphertext, wrong/missing key, write-only APIs, rollback of credential effects, sanitized errors | `encrypted_secrets_boundaries.py` |
| YAML upgrade | Fresh/empty YAML, valid ownership mapping, skipped OAuth, malformed values, backup collision, interruption before/after import commit and source retirement, repeat startup | `legacy_secrets_migration.py` |
| Schema/bootstrap | One physical target/backup, repeat startup, locked-store immutability, partial startup cleanup, unrelated database preservation | `system_database_migrations.py`, `system_startup_migrations.py`, `runtime_bootstrap_cleanup.py` |
| Public behavior | Connection CRUD/readiness, Google callbacks, Gmail reads/drafts/attachments, network and stdio MCP configuration remain compatible | `gmail_connection_api.py`, existing Gmail tool scenarios, `mcp_advanced_shell_stdio_connections.py` |

Prove atomicity through independent connections/reopened storage, not assertions
that a particular helper called `commit`. Exercise thread contention with bounded
coordination; demonstrate that no external OAuth wait holds the writer lock.
Inspect errors/events for fixture secrets, OAuth codes, and token leakage.

### Event contract

Preserve existing behavior-oriented events where their meaning survives. Remove
saga staging/retry events and tests tied solely to deleted implementation states.

| Event | Minimum safe payload | Emission boundary |
| --- | --- | --- |
| `mcp_connection_mutation_started` | `operation_id`, `connection_id`, `mutation_kind` | After identity allocation/input admission, before mutation |
| `mcp_connection_mutation_completed` | `operation_id`, `connection_id`, `mutation_kind` | Commit and manager invalidation acknowledged; never on rollback |
| `connection_mutation_failed` | `provider`, `connection_id`, `mutation_kind`, `phase`, `committed`, `error_class` | MCP transaction rollback or failed post-commit metadata/OAuth handoff; distinguish the two |
| `google_oauth_identity_changed` | `connection_id`, `config_version`, `status` | Committed credential-generation change |
| `legacy_secrets_migration_checked` | `phase`, `imported_count`, `skipped_oauth_count`, `source_retired` | Successful import/check boundary |
| `secrets_locked` | sanitized `reason` | Bootstrap rejects key/store readiness |

Operation IDs are correlation values, not persisted mutation journals. Logs are
not atomically committed with SQLite and must not be presented as exactly-once
crash-proof evidence. Record no tokens, secret values, encrypted payloads, pending
state, credential identities, or authorization URLs.

## Implementation sequence

All implementation stages are complete. Focused scenario and static-gate results
are recorded in the handoff; maintainers still own the full `integration/core`
profile.

1. **Specify and assert:** inventory mutation/storage callers and release upgrade
   sources; add the atomicity, OAuth race, and post-commit failure assertions above.
   Establish the concrete API failure projection without changing normal payloads.
2. **Build the storage foundation:** implement the small shared transaction boundary
   and final schema; add transaction-bound secret operations. Wire one physical
   migration target and safe bootstrap handling. Avoid an independently committing
   legacy path for composed writes.
3. **Migrate MCP implementation:** convert each mutation and OAuth storage guard;
   implement acknowledged post-commit invalidation; remove the journal, staging,
   cross-store fence marker, lifecycle recovery, and obsolete schema history.
4. **Migrate Google implementation:** make metadata/credential/default mutations
   atomic, retain external-request guards, move orchestration into domain services,
   and remove deferred purge and unreleased singleton/unbound-state compatibility.
5. **Complete release upgrade:** adapt YAML import to the final schema and shared
   transaction API, preserve rename recovery, and finish bootstrap/status/backup
   integration. Update isolated fixtures, CI secret seeding, and development helpers
   that name the intermediate files. No existing runtime state is reset implicitly.
6. **Simplify and document:** remove orphaned helpers, reconciliation events, and
   obsolete tests; update architecture/ADRs and product storage/backup guidance.
   Review the final diff for net reduction of lifecycle states and responsibilities.
7. **Validate and hand off:** run focused checks and the production Python quality
   gate, request maintainer full validation, and provide the narrowly scoped
   development reset instructions separately. Address failures before merge.

## Documentation and affected surfaces

- New shared storage package; `core/database.py`, `core/system_migrations.py`,
  domain schemas, and `core/runtime/bootstrap.py`.
- Secrets service/bootstrap/YAML importer, shared OAuth storage, MCP service/storage/
  manager, Google metadata/credential/OAuth services, and thin API adapters.
- Runtime/system diagnostics, database fixtures, relevant scripts, and validation.
- Revise ADR 0015 to distinguish logical ownership from physical transaction
  boundaries. Update ADRs 0034, 0035, 0037, 0038, 0041, and 0045 as needed.
- Mark ADR 0040 superseded and add a focused replacement ADR recording the shared
  SQLite transaction decision and its consequences. Preserve historical rationale
  in ADRs rather than teaching the abandoned design in product documentation.
- Update `docs/development/architecture.md`, setup/security/upgrade/backup guidance,
  project structure, and release notes to describe the final contract. Link related
  branch plans to this plan where needed; do not rewrite their execution history.

No UI redesign, broad service cleanup, transport redesign, or unrelated database
consolidation is included. Normal connection API payloads, tool names, defaults,
scope gates, shell behavior, and model-facing results remain stable.

## Completion criteria and validation ownership

- Normal connection mutations have one transaction owner and no cross-database
  journal, staged secret namespace, or deferred secret purge.
- OAuth race and principal boundaries survive, including callbacks after restart.
- Released YAML upgrades are verified and repeatable; intermediate development
  schemas have no migration/compatibility path.
- Locked stores remain untouched and diagnostic startup works.
- Runtime invalidation failure semantics are explicit and tested.
- Unrelated persistent data is untouched; no real credentials enter code/logs.
- All targeted assertions pass and the production Python gate reports zero findings:

  ```bash
  uv run ruff check .
  uv run black --check .
  uv run mypy api core
  ```

- Agents run relevant individual scenarios directly with isolated roots. Maintainers
  run `python validation/run_validation.py run integration/core`; request and record
  their results rather than running the full suite as an agent. Live Google/MCP
  reconnection checks are maintainer smoke checks, not substitutes for deterministic
  race and persistence coverage.

Next phase: maintainer-owned `integration/core` validation, followed by Commit and
Review Prep. Full-profile or live-provider findings should reopen the relevant
hardening slice; do not treat the pending merge gate as already passed.
