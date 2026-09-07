# User Documentation Merge Cleanup Plan

## Status

Implemented, including the approved README refresh and user-facing connections
guide. A
dedicated tool index will not be added: the tool references are primarily
model-facing, and the flight card already directs the model to open the file
matching a tool name or search when the mapping is not obvious. The architecture
overview, current v0.8 release notes, setup guides, use guides, tool references,
and UI-facing tool descriptions have been aligned with the current branch.

## Objective

Make the user-facing documentation describe the v0.8 branch as it will behave
after merge, give new users a discoverable path through connections and tools,
and remove factual drift between the README, setup guides, release notes, tool
references, and UI-facing configuration descriptions.

This is documentation cleanup only. It does not change API payloads, settings,
persistence, authentication, connection policy, or tool behavior.

## Priority 1: Correct Current-Contract Drift

### Import behavior

Update `docs/use/importing-content.md` to distinguish durable job creation from
execution timing:

- agent and interactive API submissions process durable jobs immediately by
  default;
- `content_import(queue_only=true)` intentionally leaves work for the background
  worker;
- queue interval and batch-size settings affect queued/background work, not the
  normal same-turn agent import path; and
- Dashboard monitoring and cancellation continue to operate on the shared
  durable job records.

Keep `docs/tools/content_import.md` as the detailed tool contract, but link it to
the importing guide. Update the `content_import` description in
`core/settings/settings.template.yaml`, which is surfaced to users, so it no
longer reads like a queue-only submission tool.

### Upgrade behavior

Align `docs/setup/upgrading.md` with the complete v0.8 migration sequence already
present in `RELEASE_NOTES.md`:

- tell every v0.8 upgrader to reconnect legacy OAuth accounts, because legacy
  OAuth state is not imported into the encrypted store;
- include the packaged-context refresh step, with the warning to preserve custom
  edits first;
- include the post-upgrade connection checks and the Gmail attachment/draft
  opt-in defaults; and
- retain the numbered-backup wording for a pre-existing
  `system/migration_backups/secrets.yaml.bak`.

### Release-note placement and wording

Move the two loose bullets above `## v0.8.0` into that release section:

- place immediate content-import behavior under `### Misc`; and
- fold the atomic `system/access.db` outcome into
  `### Protect connections and application access` in user-oriented language.

Update the legacy-secret backup sentence to mention the next numbered filename
when `secrets.yaml.bak` already exists. Keep older release sections historical;
do not rewrite them to match current behavior.

### Tool-reference corrections

- In `docs/tools/session_ops.md`, describe the tool as available to chat and
  authored scripts, including workflows, rather than only chat and context
  scripts.
- In `docs/tools/goal_ops.md`, put the `status` filter at the documented top
  level in the current-session example. The implementation accepts the nested
  compatibility form, but examples should teach one canonical payload shape.
- In `docs/use/authoring.md`, state that network/stdio MCP tools and `shell` are
  currently primary-chat capabilities, while connection-backed built-in tools
  such as Gmail can participate in normal settings-backed authoring tool
  binding when ready. This prevents authors from designing workflows around
  unavailable execution surfaces.

## Implemented: Refresh the README

The README proposal was reviewed, approved, and implemented.

### README

Refresh the feature list to include the branch's major user-visible additions:

- principal-owned Gmail and MCP connections;
- encrypted credential storage;
- explicit ingress authentication for remote deployments; and
- the optional isolated advanced shell and stdio MCP support.

Qualify the host-control statement so it remains true when advanced mode and
operator-selected mounts are enabled. Replace the requirement for an LLM API
key or OpenAI subscription with access to a supported cloud or local model;
local no-auth endpoints do not necessarily require either credential.

Add a link to the connections guide. Keep contributor architecture and
development links available, but separate them visually from the user-starting
path.

## Implemented Discoverability Decision: Connections Guide

Created `docs/use/connections.md` as the canonical user guide for **System →
Connections**. It covers:

- the shared identity model: immutable slugs, mutable display names, multiple
  accounts, and explicit defaults;
- Google client setup, callback URI use, OAuth connect/reconnect, Gmail read
  readiness, attachment-download opt-in, draft opt-in, and the fact that
  disabling drafts does not revoke Google's granted compose scope;
- MCP Streamable HTTP, SSE, and advanced-shell stdio transports;
- no-auth, bearer, header, and OAuth setup, including registered clients,
  dynamic registration, browser callbacks, and manual/headless completion;
- testing before enabling, exact tool allowlists, connection-specific private
  HTTP acknowledgement, and the trust implications of an MCP server; and
- links to `docs/tools/gmail.md`, `docs/tools/shell.md`, installation, and
  security guidance.

The short connection paragraph in `docs/setup/installation.md` now provides a
concise first-run path and links to this guide. The UI remains the source for the
exact callback URI; documentation does not hard-code deployment-specific URLs.

## Rejected Discoverability Proposal: Tool Index

Do not create `docs/tools/README.md`. The tool references are primarily provided
to the model on demand, and the flight card already tells it to read the file
matching the tool name or search when that mapping is unclear. An index would
duplicate that retrieval contract without improving the user setup path.

## Implemented Presentation Name

Use `Assistant.md` as the user-facing product name in the README, setup and use documentation, release notes, browser title, visible UI copy, and user-facing settings descriptions. Preserve `AssistantMD` in repository URLs, commands, vault paths, environment variables, headers, container names, JavaScript globals, and other technical identifiers. The installation guide explains this distinction.

## Priority 3: Improve Safety and Reference Clarity

### Security guide

Restructure `docs/setup/security.md` so encrypted credentials, Gmail, and MCP
trust are their own sections instead of nested bullets under prompt-injection
best practices. Preserve the existing boundaries, but make them easier to find.

Remove the historical claim that security instructions "successfully
innoculated" models. Recast Tavily filtering as defense in depth rather than a
guarantee that prompt injection, malicious sources, or data leakage are blocked.
The current contract is that all retrieved content remains untrusted regardless
of provider filtering.

The Gmail and MCP security sections link directly to the connections guide.

### Build and authoring guides

- Replace the two hard-coded GitHub `main` links in
  `docs/use/build-guide.md` with repository-relative links so tagged and forked
  documentation opens the matching templates.
- Add a short capability-availability note to the build guide so users can
  distinguish tools usable in authored scripts from primary-chat capabilities.
- Keep the authoring reference focused on current behavior; do not add migration
  history.

### Gmail and shell references

- Add a parameter/defaults section to `docs/tools/gmail.md`, including the
  default 25 MB attachment limit, default 50,000-character draft body limit,
  per-connection overrides, and the rule that omitting `connection` selects the
  principal's explicit default account.
- Link Gmail setup to the connections guide and reflow the existing long lines.
- Link `docs/tools/shell.md` directly to advanced-mode installation and security
  guidance, and mention `/exchange` only as an operator-created optional mount,
  not a guaranteed path.
- Update the user-facing Gmail description in
  `core/settings/settings.template.yaml` to mention unsent draft creation when
  enabled.

### Editorial consistency

Standardize tool titles on backticked tool names, use **Dashboard → ...** and
**System → ...** consistently, prefer “Markdown” for the format, and reflow long
paragraphs where touched. Do not perform a repository-wide spelling/style
rewrite unrelated to the v0.8 merge.

## Validation

Documentation cleanup should be verified with:

- a local Markdown-link check for `README.md`, `RELEASE_NOTES.md`, and all
  `docs/**/*.md` files, including relative targets and local anchors;
- searches for stale claims that all imports wait in the queue, legacy OAuth is
  migrated, MCP or shell is available to authored workflows, or credentials are
  stored in `system/secrets.yaml`;
- comparison of commands and environment variables against `.env.example`,
  `docker-compose.yml`, and `docker-compose.override.yml.example`;
- comparison of connection limits and defaults against the API/domain models;
  and
- `git diff --check` plus a final rendered Markdown review.

No scenario run is required for documentation-only edits. The maintainer-owned
integration suite is already clean for the implementation branch.

## Next Phase

Proceed to commit and merge preparation after the documentation checks pass.
