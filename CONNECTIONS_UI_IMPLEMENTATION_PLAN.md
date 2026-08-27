# Unified Connections UI and Multi-Google Plan

Implementation status: complete on `dev/mcp-experimental`.

## Objective

Make **System → Connections** a lean, unified collection of configured
connections. With no connections configured, the section contains only
**Add Google** and **Add MCP** actions. Each action opens one expanded draft
card. Saved Google and MCP connections appear together as peer collapsible
cards; deleting a connection removes its card entirely.

Extend Google to the reusable multi-connection pattern already established by
MCP: immutable IDs and slugs, unique display names, per-connection secrets,
collection CRUD, independent deletion, and one explicit default Google
connection per principal.

## User-visible contract

- The Connections section does not expose “built-in” and “MCP” subsections.
- The top row contains **Add Google** and **Add MCP** actions. Both remain
  available for additional connections.
- A new draft is expanded and is not persisted until saved. Cancelling or
  deleting an unsaved draft removes it without an API call.
- Every saved connection is one collapsible card. Its collapsed summary shows
  its display name, connection type, readiness, and connected account identity
  when available.
- Saved cards load collapsed by default so the configured connection inventory
  remains easy to scan.
- Google display names are required and unique per principal. Renaming a card
  does not change its immutable internal ID, slug, or credential ownership.
- Each Google card has **Set as default**. The first Google connection becomes
  the default automatically, and selecting another transfers the default in one
  transaction.
- When no Google connection exists, a new Google draft opens with **Set as
  default** visibly checked. The saved card keeps the checked state so a
  single-account installation never relies on an invisible default rule.
- Deleting either connection type removes its metadata and connection-scoped
  credentials, then removes the card from the UI.
- Zero configured connections returns the section to the two-button empty
  state; no empty-state panels or permanent configuration forms remain.

## Multi-Google contract

- Give each Google connection an immutable UUID, immutable readable slug, and
  mutable unique display name.
- Scope client secrets, OAuth pending state, tokens, and account identity by
  principal and connection ID, following the existing MCP credential pattern.
- Make Google API and OAuth actions connection-specific while using one stable
  installation callback URI. Cryptographic OAuth state resolves callbacks to
  connection-scoped pending attempts so simultaneous authorizations cannot
  collide.
- Keep OAuth client ID and client secret on each Google connection for the first
  iteration. Users may reuse the same Google OAuth client values across cards;
  extracting shared Google application credentials can be considered later if
  repetition proves burdensome.
- Migrate an existing singleton Google row and its encrypted credentials into
  one stable connection owned by the same principal. Preserve authorization and
  Gmail preferences without requiring reconnection where safe, and mark it as
  that principal's default.
- Maintain exactly one default whenever a principal has Google connections. A
  default cannot be unset without selecting another. Deleting the default while
  other Google connections remain requires an explicit replacement rather than
  silently changing scheduled-workflow behavior.
- Creation requests may state the default preference, but the service enforces
  the invariant: the first connection is default even if a non-UI client omits
  the field. The API response returns the effective checked state.

## Gmail selection contract

The current `gmail` tool implicitly targets the principal's only Google
connection. When multiple accounts are introduced, its account-selection
behavior is explicit and backward compatible:

- add a `connection` argument accepting the immutable readable connection slug;
- omitting it selects the principal's default Google connection, whether one or
  many accounts are configured;
- an explicit slug selects a non-default account;
- never silently search all accounts because that increases latency, result
  volume, and the chance of mixing personal and work mail unexpectedly.

The agent-visible Gmail instructions should include the ready connection names
and connected email addresses so the model can choose from user context or ask
when the intended account is ambiguous.

## Persistence and API changes

- Add a managed `connections.db` migration that introduces Google connection
  IDs and display names and changes uniqueness from principal-only to
  `(owner_principal_id, connection_id)` plus a principal-scoped normalized-name
  constraint and a single-default constraint.
- Update the built-in connection service from singleton `get/set/delete` calls
  to principal-scoped list/create/get/update/delete operations.
- Include `connection_id` in every Google secret name or namespace. Provide a
  narrowly scoped migration for the existing singleton Google secret records.
- Replace singleton Google endpoints with collection and item routes while
  keeping all responses sanitized and rejecting owner injection.
- Include the connection ID in OAuth start, pending state, completion,
  disconnect, and callback handling.
- Update Gmail readiness so the tool is available when at least one current-
  principal Google connection has the Gmail capability ready.

## Implementation slices

1. **Complete.** Build a shared connection-card shell and lean add-action row, then render MCP
   create/edit forms through that shell without changing MCP APIs.
2. **Complete.** Add the multi-Google schema, service, credential migration, and collection
   API contracts using the existing MCP identity pattern.
3. **Complete.** Convert Google OAuth and Gmail resource services to explicit connection IDs.
4. **Complete.** Render Google draft and saved cards through the shared UI, including names,
   default selection, per-card feedback, authorization, disconnect, and
   deletion.
5. **Complete.** Implement default and explicit-slug Gmail selection in chat and workflows.
6. **Complete.** Remove the permanent forms and built-in/MCP subsection disclosures, align
   current-contract documentation, and complete accessibility, responsive,
   empty-state, and mixed-card review.

## Validation targets

- Use a focused static UI contract or manual smoke check for the lean empty
  state, draft cancellation, first-Google default checkbox, collapsed saved
  cards, default indication, and mixed Google/MCP order; avoid coupling scenario
  assertions to CSS classes.
- Extend built-in connection, migration, OAuth, Gmail, and API scenarios for two
  independent Google connections, atomic default transfer, protected default
  deletion, and explicit/default Gmail selection.

## Next phase

The unified connection and multi-Google milestone is implementation-complete.
Request the maintainer-owned full validation results and proceed through review
preparation and cleanup before merge. ADR 0038 records the resulting durable
identity and default-selection decision.
