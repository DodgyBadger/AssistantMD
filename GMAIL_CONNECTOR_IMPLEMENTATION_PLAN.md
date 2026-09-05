# Native Gmail Connector Implementation Plan

## Status

Accepted; the approved read-only milestone is implementation-complete.

Completed Slice 1:

- shared provider-neutral OAuth state/PKCE/completion and encrypted storage
  primitives, with MCP regression coverage (`35edc4b`); and
- principal-owned built-in connection metadata plus typed Google/Gmail
  preferences and managed `connections.db` migration (`81ea907`).
- principal-owned encrypted Google client/token/account state, sanitized
  connection status, and scope-aware Gmail capability gating; and
- runtime-owned built-in/Google connection services that fail closed while
  secrets are unavailable.

Optional mailbox mutation slices remain unapproved and require a separate
planning and review effort.

PDF attachment download is implemented as a follow-on slice. It does not
require a broader Gmail OAuth scope.

ADR 0037 records the native connection boundary, ADR 0041 records
generation-bound Google credential mutations, and ADR 0045 records the shared
restart-safe application-owned OAuth flow.

## Objective

Add a first-class Google connection with an initial Gmail integration backed by
Google's regular Gmail API so
AssistantMD can search and read mail in chat and scheduled workflows without
depending on Google's preview MCP server, a community MCP server, or a hosted
credential intermediary.

The backend must keep Google connection configuration and OAuth credentials owned by an
explicit principal. The first frontend remains single-user and exposes only the
`local-user` connection.

## Product Contract

The initial useful release will let the local user:

1. configure a reusable Google OAuth web client in the System UI;
2. see and copy the exact AssistantMD OAuth callback URI;
3. connect or reconnect one or more Google accounts through a browser-visible,
   headless-safe OAuth flow;
4. verify the connected account and connection health;
5. let chat and scheduled workflows search Gmail and read bounded message or
   thread content; and
6. disconnect the account and remove its stored tokens.

The initial release will not send mail, delete mail, manage filters, or mutate
labels/read state. Recipient-free draft creation and bounded PDF attachment
downloads are included through the separately reviewed slices below.

Users who do not configure Gmail will see no Gmail tool in chat, delegate,
authoring, or workflow tool availability. Gmail remains an optional integration
rather than an always-present capability with a runtime configuration error.

## Architectural Decisions

### Native integration boundary

Gmail is an AssistantMD integration, not an LLM provider and not an internal MCP
server. Gmail-specific code will live under `core/integrations/gmail/`, with a
thin settings-backed tool adapter under `core/tools/` and API/UI services under
the existing System configuration surface.

This preserves the existing distinction:

- built-in tools are settings-backed, first-class AssistantMD capabilities;
- MCP remains the extension boundary for external servers; and
- model providers remain concerned only with model execution.

Tool source/provisioning and tool disclosure are separate axes:

| Provisioning category | Example | Availability |
| --- | --- | --- |
| Unconditional built-in | `file_read` | Registered and globally enabled |
| Connection-backed built-in | `gmail` | Registered, globally enabled, and the current principal has a usable built-in connection |
| External MCP | Marimo, Logfire | An enabled, usable current-principal MCP connection exposes it |

Independently, a tool may be first-class (its definition is presented directly
to the model) or search-discovered/second-class. Gmail is a connection-backed
built-in tool and is first-class for the initial implementation. MCP tools
remain search-discovered. A future built-in connection with a very large tool
catalog could be connection-backed and search-discovered without changing this
category model.

Connection gating belongs in shared capability resolution, before an agent or
authoring execution receives its effective toolset. It must apply consistently
to chat, delegates, code execution, and workflows; the Gmail tool itself must
not be attached merely to return "not configured." The existing global disabled
tool setting remains authoritative after connection gating.

For the initial contract, the Gmail capability is usable when Google client
configuration and a connected OAuth grant with the required read scope are
present. A failure discovered during a live call returns a true authentication
error and marks sanitized connection status for subsequent turns. A reconnect
required state does not expose the Gmail tool to newly constructed agents.

### Shared Google connection and principal-owned persistence

OAuth client configuration and token state will be stored in encrypted
`secrets.db` records owned by the current principal. Google authorization will
use a provider-level internal namespace such as `oauth.google`; its records will
not appear through the generic Secrets list or reveal values through API
payloads.

The connection represents one authorized Google identity, not one Google API.
Gmail is the first capability that consumes it. Future Google Calendar, Drive,
Tasks, and related integrations must reuse the same OAuth client configuration,
account identity, refresh token, refresh/locking service, callback endpoint, and
sanitized status contract.

Capability readiness is scope-aware. The presence of a Google connection alone
does not expose every Google-backed tool: Gmail requires its read scope;
Calendar will require its own approved scope; and so on. Effective tool
resolution asks the shared Google connection whether the current principal has
the scopes required by that capability.

The internal records will include, at minimum:

- OAuth client ID;
- OAuth client secret;
- pending authorization state, PKCE verifier, redirect URI, and expiry;
- access token, refresh token, token expiry, granted scopes, and token type; and
- connected Google account ID/email metadata needed for sanitized status; and
- the complete granted-scope set associated with the current token grant.

Non-secret built-in connection metadata and capability preferences belong in a
principal-owned connections store, not global `settings.yaml` and not encrypted
secret records. Introduce a subsystem-owned `connections.db` (final name subject
to the existing managed-database conventions) whose records are keyed by owner
principal and built-in connection/provider ID. The initial Google record holds
the visible client ID and Gmail capability preferences. Sensitive client-secret,
token, pending OAuth, and connected-account identity material remains in
encrypted `secrets.db`; sanitized status is derived for API/UI responses rather
than duplicated into plaintext connection metadata.

The existing MCP persistence need not migrate into this database merely to
share the System UI taxonomy. Any future persistence unification requires its
own migration justification and plan.

The settings/API contract must never return client secrets, access tokens,
refresh tokens, authorization codes, or PKCE verifiers. The owner principal ID
must be derived from execution authority, never accepted from the browser.

Multiple Google account connections are exposed for `local-user`, while Gmail
is the only implemented Google capability. Service APIs and credential storage
are principal- and connection-scoped rather than process-wide singletons. One
connection is the explicit default, and Gmail can select another by immutable
connection slug.

### OAuth deployment model

Users will create their own Google Cloud OAuth web application and enter its
client ID and secret. AssistantMD will not ship a shared Google OAuth client
secret.

The redirect URI will be built from `ASSISTANTMD_PUBLIC_URL` and a stable,
provider-level path,
for example:

`/api/system/connections/google/oauth/callback`

Automatic browser callback and manual completion will follow the established
headless-safe product pattern. Authorization attempts will use state and PKCE,
expire promptly, be single-use, and bind the callback redirect used to start the
attempt. OAuth errors will be sanitized.

The read-only milestone will request identity scopes plus
`https://www.googleapis.com/auth/gmail.readonly`. Later capabilities will use an
explicit `Add permissions`/reauthorization flow with Google's incremental
authorization behavior rather than creating a second connection. The OAuth
service will request already granted plus newly required scopes, persist the
scope set returned by Google, and verify that the required scopes were actually
granted. Existing tokens must never be treated as having newly configured
permissions.

Google does not always return a new refresh token during reauthorization. Token
updates must preserve the existing refresh token when Google legitimately omits
one, replace it when Google rotates one, and reject any result whose account
identity does not match the connected account unless the user explicitly chose
to replace the connection.

### Google OAuth boundary

Place the Google adapter under `core/integrations/google/`, separate from Gmail
resources and MIME handling. It composes the shared OAuth foundation and owns:

- Google authorization/token endpoint configuration plus offline access and
  incremental-consent parameters;
- connected Google identity lookup and account consistency checks;
- granted-scope normalization and capability checks;
- sanitized connection health and reconnect/add-permissions states; and
- Google OAuth/token error translation.

Gmail code receives a valid access token through this boundary; it does not read
OAuth secrets directly or implement refresh. Future Google integrations must do
the same.

### Shared OAuth foundation and MCP reuse

AssistantMD already has a proven OAuth authorization-code/PKCE implementation
for MCP connections. Refactor reusable mechanics from `core/mcp/oauth.py` and
`core/mcp/oauth_storage.py` into a narrow shared OAuth foundation before adding
Google-specific duplication. The shared layer should cover:

- state and PKCE generation/verification;
- expiring, single-use pending authorization records;
- canonical callback/manual completion parsing;
- encrypted principal-owned JSON/token record storage;
- authorization-code exchange and refresh-token requests over hardened async
  HTTP;
- safe token merge rules and expiry handling; and
- sanitized protocol errors and authorization attempt status.

MCP remains an adapter over that foundation. It continues to own protected
resource metadata discovery, authorization-server metadata, dynamic client
registration or pre-registered clients, MCP resource indicators, FastMCP token
adapters, per-connection namespaces, and MCP manager invalidation.

Google is a second adapter. It owns fixed Google authorization/token endpoints,
offline/incremental-consent parameters, Google account identity verification,
scope semantics, and provider-specific refresh/revocation errors.

Do not force provider-specific behavior into a lowest-common-denominator API.
The goal is one protocol foundation with explicit provider adapters, not one
configuration model pretending every OAuth server behaves identically. Existing
MCP OAuth scenarios are mandatory regression coverage for this extraction,
including dynamic registration, pre-registered clients, proactive discovery,
headless completion, encrypted tokens, and browser-visible callbacks.

### Gmail API client

Use Google's documented HTTPS endpoints directly through a small typed,
asynchronous service boundary. Do not add `google-api-python-client`,
`google-auth-httplib2`, or `google-auth-oauthlib` for the first implementation.

This is a deliberate integration choice rather than a rejection of Google's
contracts. Gmail is an HTTP/JSON API and Google documents direct REST as a
supported calling method. The generated Python client is synchronous,
discovery-driven, and normally coupled to `httplib2`; adapting it would add a
thread boundary and a second HTTP/retry stack to an asynchronous application.
The read-only Gmail milestone needs only a small, stable subset of resource
endpoints:

- `users.getProfile`;
- `users.messages.list` and `users.messages.get`; and
- `users.threads.get` (with thread listing deferred unless a concrete tool need
  emerges).

Define strict Pydantic response models for only the fields AssistantMD consumes
and retain bounded handling for unknown fields. Use `format=metadata` for
envelope hydration and `format=full` only for an explicit message/thread read;
never request `raw` in the read-only milestone. This keeps search results small
and leaves MIME normalization under an explicit, testable boundary.

The transport will:

- use the existing `default_api_timeout` setting for each external request;
- refresh access tokens before expiry;
- retry rate limits, retryable Google 5xx responses, and network failures using
  the project's bounded retry conventions;
- honor `Retry-After` where supplied;
- never retry permanent authorization or validation failures blindly;
- use bounded timeouts and response sizes; and
- translate Google errors into stable internal categories and concise,
  model-visible tool failures.

The initial Google retry policy is fixed rather than user-configurable: three
attempts total for network failures, HTTP 429, Google retryable quota/rate-limit
403 reasons, and HTTP 500/502/503/504. Respect `Retry-After`; otherwise use
jittered exponential backoff. Authentication, permission, validation,
not-found, and other permanent failures are not automatically retried. The
existing model-stream retry settings do not apply to connector traffic, while
`workflow_task_timeout_seconds` remains the outer bound for a workflow run.

Token refresh writes must preserve the principal owner and be concurrency-safe
so simultaneous chat/workflow calls do not corrupt or discard a rotated refresh
token.

### Pydantic AI responsibility

Pydantic AI does not provide a Gmail API client or Google Workspace OAuth
connector. Use it at the model-facing boundary only:

- define the typed `gmail` tool arguments/results;
- attach the tool through the existing `FunctionToolset` capability path;
- omit it during effective tool resolution when the connection is unusable;
- carry AssistantMD recovery/source metadata; and
- reuse the existing tool lifecycle and oversized-output cache capabilities.

Do not use Pydantic AI model-request retries for Gmail calls. Gmail transport
retries belong below the tool in the integration client so chat and workflows
receive the same behavior and individual Gmail requests—not whole model turns or
completed tool effects—are retried.

Pydantic AI deferred approval is not needed while Gmail is read-only. Revisit it
only for future mutating operations, alongside workflow policy and ambiguous
external-effect recovery.

### Tool shape and context safety

Register one built-in `gmail` tool through the existing settings-backed tool
registry. Its concise definition will point to a virtual tool document for full
usage guidance, consistent with ADR 0008.

Initial operations:

- `status`: report sanitized account/readiness metadata;
- `search`: run a Gmail query with bounded pagination and return message/thread
  IDs plus compact envelope metadata and snippets;
- `get_message`: fetch one message with bounded normalized text and attachment
  metadata; and
- `get_thread`: fetch a bounded thread with explicit truncation metadata.

Principal-owned Gmail capability preferences:

- `search_default_results`, default `20`;
- `search_max_results`, default `100`, with a fixed internal ceiling of `500`;
- `message_max_characters`, default `50000`, with a fixed internal ceiling of
  `250000`; and
- `thread_max_messages`, default `25`, with a fixed internal ceiling of `100`.

`search` accepts an optional requested result count. Omission uses the configured
default; a larger request is capped by the configured maximum and reports that
fact. Message and thread reads report character/message truncation and omitted
counts. These limits bound fetching and normalization before the existing
oversized tool-output cache protects chat context.

Message identifiers returned by search are the handles for subsequent reads.
Search will not eagerly inject complete message bodies. Responses will carry
stable truncation/pagination fields, and oversized results will continue through
the existing chat tool-output cache capability.

Message/thread results include attachment descriptors only: attachment ID,
filename, media type, declared size, and containing message ID. Return at most
100 attachment descriptors per message with explicit truncation metadata. The
tool does not download, decode, cache, or return attachment bytes/base64 and has
no `get_attachment` operation in this milestone.

Email headers, subjects, snippets, and bodies are untrusted external content.
Tool results and tool documentation will clearly mark that boundary and instruct
the model not to follow instructions found in email. Raw HTML will not be
returned in the first release; MIME content will be normalized to bounded plain
text with predictable preference for `text/plain` and a conservative HTML
fallback.

The tool's interruption recovery policy is `replay_safe` while it is strictly
read-only.

### Workflow behavior

Scheduled workflows use the workflow owner's principal authority and resolve
that owner's Google connection and Gmail scope. The currently accepted
`local-user` inheritance therefore works without a scheduler-specific Gmail
credential.

Missing, expired, revoked, or insufficient authorization must produce a true
connection/authentication failure, not an empty mailbox result. Workflows will
record the existing terminal failure information without logging email content
or credential material.

### Future deterministic ingestion compatibility

Do not implement Gmail ingestion in this effort, but keep the Gmail API client
and normalized resource models independent from the model-facing `gmail` tool.
Both the tool and a future ingestion source importer must be able to call the
same principal-authorized Google/Gmail resource service.

The future flow should be deterministic:

```text
scheduled/manual workflow
  -> Gmail query/resource service
  -> stable connected-source references
  -> durable ingestion jobs
  -> Gmail source importer
  -> RawDocument
  -> existing extraction/rendering/vault-mutation pipeline
```

This follows ADR 0011: Gmail knows how to load a connected source into a
`RawDocument`; extraction/rendering remains an ingestion concern. It also
follows ADR 0029: query policy, incremental cursors, filter selection,
source-level deduplication, retry/resumption policy, and library organization
remain workflow concerns rather than becoming hidden ingestion orchestration.

Preserve enough typed source identity and metadata now to support that adapter
later without changing the chat contract:

- provider and resource kind (`google`, `gmail_message`/`gmail_thread`);
- connected Google account identity, resolved internally rather than supplied
  as authority by the caller;
- immutable Gmail message/thread ID;
- Gmail `historyId` and message `internalDate` when available;
- MIME type, filename, and attachment identifiers as metadata only; and
- a stable source-display/provenance label that does not expose credentials.

The tool may format these models compactly for an LLM, but provider resource
models must not depend on Markdown presentation or tool result strings. A
future importer should accept a typed connected-source reference, resolve it
under the workflow's execution authority, fetch the resource through the shared
Gmail service, and submit content through the existing durable ingestion job,
activity, and vault-mutation paths.

No mailbox sync database, history cursor, ingestion source URI syntax,
automatic Markdown layout, or Gmail-specific workflow is part of the current
contract. Downloads produce ordinary vault files; downstream systems remain
independent.

The Gmail tool can perform a bounded authenticated PDF attachment download to a
caller-selected vault path. It returns only sanitized metadata and the created
path. Any later import, conversion, or shell processing is a separate user- and
agent-directed operation.

## User Interface and API Surface

Add a `Connections` section to the System tab rather than placing Google among
model providers. It contains two subsections:

- `Built-in connections`, whose first card is Google; and
- `MCP connections`, containing the MCP connection management UI already built.

This is a UI and configuration taxonomy, not a claim that built-in and MCP tools
share their transport, credential, discovery, or lifecycle implementation. The
Google card contains:

- connection state (`Not configured`, `Ready`, `Reconnect required`, or
  `Error`);
- sanitized connected email/account information;
- configured callback URI with copy affordance;
- a visible/editable client ID plus a write-only client secret input and secret
  presence indicator;
- ordered actions: `Save configuration`, `Authorize Gmail`, `Check connection`,
  and `Disconnect`;
- authorization URL and manual completion controls when a flow is pending; and
- a concise explanation of the currently granted scopes and the Gmail
  permission requested by this release.

Within the Google card, show Gmail as the first supported capability and its
readiness. Future Calendar or Drive work extends this card instead of adding
independent OAuth cards and tokens.

The backend API will expose sanitized endpoints for configuration, OAuth start,
callback/manual completion, status/test, and disconnect. Exact models should
follow existing configuration response/error conventions and must not expose an
owner selector.

Missing `ASSISTANTMD_PUBLIC_URL` will leave the application available but block
starting Google OAuth with an actionable System message. Unlike generic MCP,
Google web-app redirect registration needs one canonical callback and should not
silently select a request-derived production origin.

## Activity and Logging Contract

Emit decision-boundary events without mailbox content, Gmail queries, URLs with
query strings, authorization codes, or credentials:

- `google_configuration_updated`: `principal_id`, client-ID/secret presence;
- `google_oauth_started`: `principal_id`, redirect source, requested scope names;
- `google_oauth_completed`: `principal_id`, connected account identifier/email,
  granted scope names;
- `google_oauth_disconnected`: `principal_id`;
- `google_token_refresh_failed`: `principal_id`, stable failure category; and
- `gmail_api_request_failed`: `principal_id`, operation, HTTP status when safe,
  stable failure category, retryable flag.

Successful searches and reads should rely on normal tool-call activity rather
than duplicating mailbox-specific success logs. Logs must not contain message
IDs if the existing activity contract treats external resource IDs as sensitive;
that point will be resolved during the first validation slice.

## Implementation Slices

### Slice 1: Executable contracts and domain skeleton

- Add failing deterministic scenario assertions for principal isolation,
  sanitized status, locked-secrets behavior, OAuth callback construction, and
  read-only tool registration.
- Add characterization assertions around the existing MCP OAuth flow, then
  extract the shared OAuth protocol/storage primitives without changing its
  public API or behavior.
- Define typed Google connection/Gmail capability status models and stable error
  categories.
- Add the principal-owned built-in connection metadata schema/service and Gmail
  preference validation, isolated from encrypted credential storage.
- Establish the shared Google OAuth secret namespace, scope-aware capability
  checks, and metadata-only access helpers.
- Define a shared, typed connection-backed availability contract and assert
  that Gmail is absent from effective tool bindings until its principal-owned
  Google connection is usable and has the Gmail read scope.
- Add a short ADR recording the native-integration boundary if implementation
  reveals that existing ADRs do not fully settle it.

Validation target: new
`validation/scenarios/integration/core/gmail_principal_connection.py` plus the
existing MCP OAuth coordinator/storage scenarios.

### Slice 2: OAuth configuration and connection UI

Status: complete. The reusable Google OAuth coordinator, fixed public callback,
encrypted grant lifecycle, principal-owned API, and grouped Connections UI are
implemented. Deployed Gmail authorization remains the manual checkpoint before
the Gmail resource client is bound to chat.

- Implement the reusable encrypted principal-owned Google client configuration
  and pending/connected OAuth state.
- Implement Google authorization, callback, manual completion, refresh, status,
  test, and disconnect services.
- Add System API models/endpoints, the parent Connections section, the Google
  built-in connection card with Gmail capability status, and move the existing MCP UI beneath the MCP
  connections subsection without changing its API/runtime contract.
- Validate exact public callback behavior, state/PKCE binding, pending expiry,
  replay rejection, reconnect behavior, secret redaction, and account identity
  lookup.

Manual checkpoint: connect a disposable personal Gmail test account from the
deployed/headless environment and confirm automatic plus displayed/manual URL
behavior.

### Slice 3: Read-only Gmail client and built-in tool

Status: complete. The bounded Gmail REST/resource service, MIME normalization,
attachment descriptors, retry policy, virtual tool documentation, and
connection-gated first-class `gmail` tool are implemented. The configured local
account passed a live read-only search smoke check without exposing message
content in validation output.

- Implement bounded Gmail REST operations, MIME normalization, pagination, and
  retry/error translation.
- Apply the accepted principal-owned search/read preferences, shared API timeout,
  and fixed Google retry policy.
- Keep normalized Gmail resource/query models and the principal-authorized
  resource service independent from LLM formatting so a future ingestion source
  importer can reuse them directly.
- Return bounded attachment descriptors in message/thread tool metadata while
  prohibiting attachment content downloads in this milestone.
- Add the settings-backed `gmail` tool and concise virtual documentation.
- Bind it through chat, delegate, code execution, and workflows using the shared
  built-in tool path only while the current execution principal has a usable
  Google connection with the required Gmail scope and the tool is not globally
  disabled.
- Mark all returned email content as untrusted and verify cache/truncation
  behavior.

Validation target: new
`validation/scenarios/integration/core/gmail_read_tools.py` with a deterministic fake
Google HTTP service. Assert request shape and stable tool artifacts rather than
LLM prose.

Manual checkpoint: ask chat to find and summarize known messages in the test
account, then run a one-off read-only workflow under `local-user`.

### Slice 4: Workflow hardening and operational polish

Status: complete. Concurrent token refresh, retryable provider responses,
timeouts, revoked authorization, empty results, partial pages, malformed MIME,
bounded content, and scheduled-workflow authority now have deterministic
coverage. Operational logs and current-contract security/runtime documentation
avoid message content and credential material.

- Exercise concurrent token refresh from chat and workflow paths.
- Confirm revoked grants, insufficient scopes, rate limits, network timeouts,
  partial pagination, malformed MIME, and oversized bodies fail predictably.
- Ensure workflow failures distinguish authentication failure from a successful
  empty search.
- Complete architecture, installation, System UI, tool, security, and workflow
  documentation describing only the resulting contract.

Validation target: extend the Gmail scenarios and the most relevant existing
workflow principal scenario; do not create assertions around free-form model
summaries.

### Slice 5: Optional mailbox organization (separate approval)

After read-only use is proven, consider label application/removal and mark
read/unread. This requires `gmail.modify`, an explicit scope-upgrade and
reconnection UX, non-replay-safe recovery metadata where appropriate, and a
clear workflow mutation policy. Archive, trash, delete, and filter management
remain out of scope unless separately approved.

### Slice 6: Draft creation

Status: implementation complete; targeted validation passed.

Add draft creation as an opt-in, per-connection Gmail capability. Drafting and
sending remain distinct AssistantMD capabilities even though Google's
`gmail.compose` scope technically authorizes both. AssistantMD must never bind
or call a send endpoint merely because a connection has that OAuth grant.

The first drafting slice creates new, plain-text drafts only. It does not send,
update, delete, or attach files; choose arbitrary `From` identities; or construct
threaded replies. Those extensions require their own concrete contracts.

#### Recovery and transaction boundary

Draft creation is a remote mailbox mutation, not a vault transaction. Gmail's
successful `drafts.create` response supplies the durable draft ID, but a network
failure can occur after Google commits the draft and before AssistantMD receives
that response. Gmail documents no idempotency-key contract for draft creation.
Automatic POST retry could therefore create duplicates, while vault rollback
cannot undo the remote effect.

Change the single Gmail tool's recovery policy to `MANUAL_REQUIRED` when draft
creation lands. The current recovery ledger records an unresolved effect by
tool name, not operation, and bound-tool recovery metadata is static. Do not
misclassify remote draft mutation as `VAULT_TRANSACTIONAL`, automatically replay
it, persist draft bodies in recovery metadata, or expand the recovery framework
solely for this slice.

This conservative policy matters only when a Gmail tool call is unresolved
during a retryable run failure. Completed draft calls already have settled tool
returns and resumable snapshots. An ambiguous draft-create failure must tell the
user that the draft may exist and recommend inspecting Gmail drafts before
retrying. Ordinary provider validation errors are definite failures. Mutating
requests use one network attempt; they do not inherit the read client's 429/5xx
retry loop.

A future operation-aware recovery design may record a non-sensitive operation
class alongside each tool effect, but must not persist recipients, subjects, or
bodies. A future reconciliation design may generate an RFC Message-ID and query
drafts by `rfc822msgid`, but search consistency is not a sufficient transaction
guarantee for the initial contract.

#### Capability and OAuth contract

- Add `draft_creation_enabled` to each Gmail connection, default `false` for
  new and migrated connections. Gmail read and attachment settings remain
  independent.
- Add `GMAIL_COMPOSE` to the Google capability model, requiring identity scopes
  plus `https://www.googleapis.com/auth/gmail.compose`.
- When draft creation is enabled, the connection UI reports whether compose
  permission is present and offers the existing incremental authorization flow
  to add it. Enabling the preference alone never implies that the scope exists.
- Runtime draft creation requires both the selected connection's opt-in and its
  usable compose grant. Resolve both against the same principal-owned connection
  ID before constructing the Gmail client.
- The Gmail tool remains available for reading when compose permission is
  absent. `status` and `connections` expose sanitized draft opt-in, readiness,
  and missing-scope information so chat can inspect capability without failing
  a mutation.

#### Draft creation contract

Add `create_draft` to the existing `gmail` tool with bounded inputs:

- required `subject` and plain-text `body`;
- no recipient fields; the user adds recipients while reviewing in Gmail;
- strict rejection of control characters in the subject header;
- a per-connection `draft_max_characters` preference with a fixed internal
  ceiling; and
- no caller-supplied `From`, raw MIME, HTML, attachments, or send behavior in
  this slice.

Build standards-compliant RFC 2822 MIME with Python's email package and submit
base64url content to `POST /users/me/drafts`. Treat all composed fields as
sensitive: do not put subject, body, raw MIME, or provider response content in
operational logs. Subject and body remain in the ordinary persisted chat
tool-call record, consistent with other chat and Gmail content. Return only
sanitized connection identity, draft ID, message ID, and thread ID. Log
start/completion/failure with principal, connection, stable category, and body
character count only.

The tool description and virtual documentation must state that creation only
saves an unsent Gmail draft. Connection opt-in authorizes chat and owning
workflows to create drafts without per-call approval; it never authorizes send.

Validation target: deterministic Gmail HTTP scenarios for exact MIME shape,
base64url encoding, header validation, input bounds, selected-account
isolation, opt-in plus scope gating, incremental scope requests, sanitized
results/logs, definite 4xx failure, and ambiguous timeout/5xx behavior with no
automatic POST replay. Extend recovery-policy coverage to prove unresolved
Gmail effects select manual recovery and never vault rollback/restart. Add a
populated prior-schema migration scenario proving existing connections default
draft creation to disabled.

Manual checkpoint: incrementally authorize a disposable Gmail account, create a
recognizable draft from chat and an owning workflow, verify it remains unsent,
and confirm a read-only connection still works without compose permission.

### Future sending capability (separate approval)

Sending requires a separate per-connection opt-in even when `gmail.compose` is
already granted. It also requires explicit policy for recipient/content review,
unattended workflows, ambiguous delivery, duplicate-send prevention, and audit
metadata. No send capability should be introduced as part of draft creation.

### Slice 7: PDF attachment download

Status: complete. Gmail can copy a bounded PDF attachment to an arbitrary
vault-relative path without selecting or invoking a downstream workflow.

Add `download_attachment` to the existing connection-gated `gmail` tool. Gmail
is the cohesive user-facing capability, and its operation surface may expand
beyond mailbox reads over time; attachment retrieval does not justify a second
tool.

At the attachment-only stage, Gmail's declared policy changed from
`REPLAY_SAFE` to `VAULT_TRANSACTIONAL`, matching the vault-writing boundary.
Draft creation subsequently required the tool-wide `MANUAL_REQUIRED` policy
documented in Slice 6 because recovery metadata is not operation-specific. A
failure before the vault write has no durable effect; the vault mutation
subsystem records the write itself. Do not
expand the recovery framework merely for this slice.

The Gmail tool has exactly one responsibility for this operation: copy the
selected attachment into an arbitrary caller-supplied vault-relative path and
return the resulting path. Its responsibility ends once that vault write
succeeds. Gmail must not enqueue an ingestion job, choose a downstream
workflow, or coordinate a transaction with another subsystem.

What happens next is decided by the user and agent. They may pass the returned
path to `content_import`, move or retain the original, or make it available to
the advanced shell for operations such as splitting, merging, or adding pages.
Those are independent tool calls with their own authorization and recovery
contracts.

For the initial slice:

- accept an exact message ID, attachment ID, and optional Google connection
  slug returned by the existing Gmail reader;
- resolve the principal-owned connection through `GmailResourceService` and
  download the attachment synchronously while the caller's execution authority
  is available;
- verify that the selected attachment belongs to the message, enforce a bounded
  declared and decoded size, validate PDF media type/signature, and never return
  attachment bytes to the model or logs;
- add an opt-in attachment-download capability and maximum size to each Gmail
  connection, defaulting existing and new connections to disabled with a 25 MB
  limit; enforce the limit against both declared and decoded size without
  disabling Gmail reads;
- require an arbitrary vault-relative destination path, validate it through the
  existing vault boundary, write the attachment there through the vault mutation
  subsystem, and return the path actually used; never overwrite an existing
  file and require no collision-control parameter—if the requested name exists,
  append an incrementing suffix before the extension (for example,
  `report.pdf`, `report (1).pdf`, `report (2).pdf`); select and create the path
  atomically so concurrent downloads cannot claim the same numbered version;
- return only sanitized attachment/source metadata useful for subsequent agent
  decisions, without treating message content or filenames as trusted input;
- expose the operation through the existing Gmail capability and its
  `google.gmail.read` connection requirement. The existing `gmail.readonly`
  grant is sufficient, so no Google reconnection or scope migration is needed.

Keep the transport and vault-write implementation media-type neutral even
though the initial product contract accepts PDFs only. Adding DOCX and other
approved attachment types later should primarily extend an allowlist and
validation policy rather than require a new download architecture.

Do not implement `SourceKind.MAIL` as a background fetch for this slice.
Ingestion workers do not carry the submitting execution authority, and jobs do
not persist an owner plus exact Google connection identity. A true mail-source
worker would therefore require a job-schema migration, authority-safe credential
lookup, connection revocation/deletion semantics, and new retry/provenance
behavior. A completed vault download is already a durable ordinary file that
any authorized downstream tool can consume.

Validation target: extend the deterministic Gmail HTTP scenario for attachment
ownership, base64url decoding, malformed payloads, MIME/signature mismatch,
declared/decoded size limits, connection isolation, safe path handling, vault
mutation behavior, overwrite/collision policy, and returned metadata. Existing
vault-file consumers remain independently responsible for their own scenarios;
do not couple this Gmail slice to `content_import` or advanced-shell behavior.
Maintainers run the full validation suite.

Estimated implementation effort is one-and-a-half to three focused engineering
days, including targeted scenarios, documentation, security review, and
cleanup. A true background `MAIL` source is a larger five-to-eight-day change.
A graphical mailbox attachment picker is outside this estimate and would add
API/frontend work; the candidate slice is chat- and workflow-driven.

## Security Invariants

- Google credentials are encrypted, principal-owned, and hidden from generic
  secret enumeration.
- The browser cannot choose or inspect a principal ID.
- OAuth state is expiring, single-use, PKCE-bound, and callback-bound.
- Logs, API errors, activity records, and validation artifacts contain no token,
  authorization code, client secret, raw email body, or sensitive OAuth URL.
- A missing or locked secrets database disables Google connection configuration
  and Gmail use without modifying encrypted records.
- Gmail mutation is limited to explicitly enabled draft creation; no send,
  mailbox-state, or deletion operation is exposed.
- Email content is treated as untrusted data, never as tool or system
  instructions.
- Scheduled workflows use only their owning principal's Google connection.
- Unconfigured or reconnect-required Gmail never appears in the effective tool
  set for a newly constructed execution.
- An API failure is never represented as an empty successful search.
- Gmail resource models retain stable external source identity/provenance fields
  without coupling the current feature to ingestion jobs or sync state.
- Gmail tool results expose no attachment bodies; attachment IDs remain opaque
  authority-checked handles used to download into the vault.

## Documentation Impact

Update, as the implementation slices land:

- `.env.example` and installation guidance for canonical public URL dependency;
- System configuration documentation for creating a Google OAuth web client and
  registering the displayed redirect URI;
- `docs/development/architecture.md` for the native connection, capability, and
  credential boundaries;
- a Gmail tool document under `docs/tools/`;
- workflow guidance for owner-scoped Gmail access; and
- security guidance covering mailbox prompt injection, scopes, revocation, and
  test-mode token expiry.

Product documentation will describe the current Gmail contract. Upgrade or
migration notes will be isolated to release/installation material only if a
real migration is introduced.

## Resolved Review Decisions

- Gmail reads request `gmail.readonly` plus identity scopes. Connections with
  draft creation enabled additionally request `gmail.compose`.
- The Google client ID is visible/editable after save; the client secret remains
  write-only.
- A configured `ASSISTANTMD_PUBLIC_URL` is required to start Google OAuth.
- The implementation uses direct asynchronous REST calls over the existing HTTP
  and retry stack rather than adding Google's generated Python client.
- Gmail search/read limits are principal-owned built-in connection preferences;
  secrets remain separately encrypted.
- Gmail requests reuse `default_api_timeout`; Google retry behavior is a fixed,
  bounded three-attempt policy in the first iteration.
- Gmail message/thread results expose at most 100 attachment descriptors per
  message. Exact PDF attachment handles can be downloaded to the vault without
  coupling Gmail to ingestion or later processing.
- Google OAuth/token/identity/scope handling is a reusable principal-owned
  connection boundary shared by future Google capabilities.
- State/PKCE, pending-flow, encrypted token-storage, token-exchange, and refresh
  mechanics reuse a shared OAuth foundation extracted from the proven MCP flow;
  MCP and Google retain explicit provider/protocol adapters.
- Pydantic AI owns typed tool exposure and lifecycle integration, not Gmail
  transport or Google OAuth.

Using a disposable Gmail account is optional manual-testing guidance, not a
product or implementation decision. Multi-account selection follows ADR 0038.
Sending, deletion, and other mailbox mutation remain outside the approved
capabilities.

## Delivery and Validation Gates

Each slice should be committed independently after its targeted scenario and
smoke checks pass. Before any production-Python commit or final handoff, run:

`uv run ruff check . && uv run black --check . && uv run mypy api core`

Run relevant JavaScript syntax checks and `npm run build:css` only when their
sources change. Maintainers, not agents, run the full validation suite; request
full-suite results before merge.

## Next Phase

Request the maintainer-owned full validation results and proceed through review
preparation and cleanup before merge. ADR 0037 records the native
connection-backed integration boundary. Sending or any additional mailbox
mutation requires separate approval and a new or updated root implementation
plan.
