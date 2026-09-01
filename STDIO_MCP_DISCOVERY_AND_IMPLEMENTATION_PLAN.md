# Stdio MCP Discovery and Implementation Plan

## Status

Discovery experiments A through D are complete. The advanced shell,
authenticated SSH transport, structured launch boundary, and representative MCP
client capability matrix are validated. The smallest persisted stdio connection
shape is now selected below. Repository research and live testing show that
`command + args` describes only the process launch boundary. It does not
adequately describe how many useful MCP servers are installed, granted
filesystem scope, initialized, kept aligned with agent instructions, or
operated after startup.

The initial connector is now implemented across schema migration, domain/API
models, advanced-mode mutation gates, the retained MCP manager, fixed SSH stdio
transport, Roots, strict YAML/JSON import, System UI create/edit/test flow, and
the bundled Advanced Shell MCP Setup skill. Deterministic stdio integration coverage
and a live filesystem-server manager probe pass. Maintainer validation and a
manual browser workflow remain before the slice is considered merge-ready.

The first live agent-assisted setup also completed end to end with
`paper-search-mcp`: installation, compatibility recovery, SDK initialization,
tool discovery, import, reviewed skill creation, deferred tool search, and a
real provider call all succeeded. The bundled setup skill is hardened from that
run to require exact provider version pins, official-SDK probes, explicit
warning assessment, bounded risk-oriented tool-inventory review,
version-matched provider-skill provenance, and registered-MCP-first use.
Advanced-shell credentials remain a
possible user-managed escape hatch, but AssistantMD does not currently manage,
encrypt, back up, or inject them. Any credential stored in the advanced shell is
readable by the chat agent through `shell`, so that choice explicitly grants the
agent access to the credential.

The clean second paper-search run validated the hardened workflow without
repeating connection registration: installation and verification fell from
roughly six minutes and fourteen shell calls to roughly two minutes and eleven
shell calls, with no protocol-framing detour or timeout. It pinned
`paper-search-mcp==0.1.4`, recovered the upstream `mcp<2` packaging constraint,
used the provider environment's official SDK, fetched the matching tagged
skill, and produced a registered-MCP-first adaptation. The remaining repeated
friction was oversized web-result retrieval and verbose inventory output. The
model-visible cache notice now states that `read_cache` returns a
`RetrievedItem` and directs use of `artifact.content`; the setup skill now asks
for compact, risk-oriented inventory summaries rather than every full schema.

This plan deliberately precedes connector implementation. It updates the
problem definition and defines the experiments needed before changing the MCP
database or System UI.

The first implementation increment adds a versioned structured-launch mode to
the advanced-shell forced-command wrapper plus a non-persisted FastMCP probe. A local
adversarial wrapper test proves argv metacharacters remain literal, relative
executables and non-canonical working directories fail closed, bounded
non-secret environment is constructed explicitly, and the prior
descendant-cleanup contract still passes. The rebuilt development advanced shell ran
fixed installed Python and npm executables through the structured mode, and all
three representative MCP sessions initialized, listed capabilities, completed
tool calls, closed, and left no provider processes behind.

The first live run also proved why connection testing must never install at
launch: `npx` wrote package-install output to stdout and caused repeated MCP JSON
parse errors before the client recovered. After provisioning each executable
once and launching its fixed path, the same probe completed without framing
pollution.

## Objective

Find the smallest user-friendly contract that lets an advanced-mode user make a
trusted, credential-free stdio MCP provider available through AssistantMD's
existing governed MCP pipeline without turning AssistantMD into a general
package manager or silently treating third-party instructions as trusted system
prompt content.

The design must preserve:

- one fixed advanced-shell destination rather than per-connection SSH targets;
- principal-owned connection identity and immutable model-facing slugs;
- exact-name allowlisting, frozen catalogs, and deferred tool disclosure;
- bounded process lifecycle, cancellation, activity, and result shaping;
- advanced-mode gating at API, test, acquisition, and chat boundaries;
- the existing rule that MCP server instructions are not automatically injected
  into chat; and
- the initial advanced-shell credential boundary.

## Revised Problem Definition

A usable local MCP integration may have three independent artifacts:

1. **Provisioned runtime** — a package, repository checkout, release binary,
   generated files, subordinate services, or language-specific dependencies in
   the advanced shell.
2. **Launch definition** — the executable, ordered arguments, working directory,
   non-secret environment, and any client capabilities needed for one stdio
   session.
3. **Agent guidance** — optional version-coupled instructions such as
   `SKILL.md`, supporting references/scripts/assets, an MCP prompt, or a short
   usage policy explaining how and when to use the tools.

These artifacts should not be collapsed into one persisted shell recipe:

- installation is mutable infrastructure work and can execute arbitrary code;
- launch configuration is durable connection metadata and must be deterministic;
- agent guidance is untrusted instruction content with its own disclosure,
  review, versioning, and prompt-injection concerns; and
- package upgrades can change the executable or tool catalog without updating a
  separately copied skill.

The initial connector therefore should not promise one-click installation from
arbitrary repositories. The likely first boundary is: install and configure the
runtime through advanced shell, then register a deterministic launch definition
through AssistantMD. Optional agent guidance must use an explicit AssistantMD
instruction/skill pathway rather than being silently copied into the flight
card or accepted from MCP initialization.

## Representative Server Findings

### `mcp-server-fetch`: minimal Python package

Prior live advanced-shell testing installed this credential-free package under the
persistent home, launched it over stdio, initialized it, discovered `fetch`, and
completed a call without a lingering process.

It represents the narrow case:

- Python/uv installation;
- one executable with no required launch arguments;
- no persistent provider data;
- no separate usage skill; and
- outbound network access as the substantive runtime permission.

This proves the transport, but it is not representative enough to define the
configuration model.

### `@modelcontextprotocol/server-filesystem`: launch-time authority

The official filesystem server is installed/run with npm, but it requires at
least one allowed directory. It accepts directories as ordered command
arguments or requests MCP Roots from a capable client. An empty argument list
without usable Roots fails initialization. The configured paths are advanced-shell
paths and are meaningful only in relation to the deployment's selected mounts.

Implications:

- arguments can be security authority, not mere process syntax;
- connection testing needs the same mount and Roots context as real use;
- AssistantMD must decide whether its first stdio client advertises Roots;
- UI path selection cannot imply visibility that the advanced shell does not have;
  and
- arbitrary path arguments are inspectable configuration but cannot be
  validated completely from the AssistantMD filesystem namespace.

Reference: <https://github.com/modelcontextprotocol/servers/blob/main/src/filesystem/README.md>

### Obscura: self-contained stateful binary

Prior live testing installed checksum-verified release binaries into persistent
home and ran the default `obscura mcp` stdio server. The provider carries its own
browser engine, exposes optional launch flags, and maintains a live browser
session across related tool calls.

Implications:

- an executable may be a downloaded artifact rather than a package-manager
  entrypoint;
- retained MCP client lifetime is observable provider state;
- installation footprint and archive staging matter independently of launch;
- connector restart semantics can discard useful session state; and
- optional flags such as proxy configuration may cross the initial
  credential-free boundary and must not be generalized prematurely.

Reference: <https://github.com/h4ckf0r0day/obscura/wiki/Use-the-MCP-server>

### `lsp-mcp-server`: dependency graph plus versioned skill

This server is cloned, installed, and built from a repository, then launched
with Node against a built entrypoint (or linked globally). Its usefulness also
depends on separately installed language servers, mounted source workspaces,
and sometimes non-secret environment configuration. The repository ships a
recommended `SKILL.md` that documents tool-selection rules, workflows, errors,
and output shapes. Its documentation explicitly recommends keeping that skill
aligned with the server version.

Implications:

- “install server” may mean building source and provisioning subordinate
  executables;
- readiness can be partial: the MCP process is healthy while no desired
  language server is available;
- a workspace mount is part of the capability's meaning;
- the launch definition alone cannot teach the model to use a large catalog
  effectively; and
- skill import/version alignment is a separate lifecycle from MCP connection
  retention.

Reference: <https://github.com/ProfessioneIT/lsp-mcp-server/blob/main/README.md>

### `skills-mcp`: instructions that assume agent filesystem execution

This npm stdio server requires one or more absolute skill-directory paths. It
can return skill metadata and `SKILL.md` content, and offers an initialization
prompt, but its documented workflow expects the agent itself to read referenced
files and execute scripts at returned advanced-shell paths.

Implications:

- MCP tools, prompts, resources, and external skill files are different
  disclosure mechanisms;
- AssistantMD currently excludes MCP server instructions and does not compose
  MCP prompts/resources into chat;
- a path returned by an advanced-shell provider is not readable through AssistantMD's
  normal vault file tools;
- primary advanced chats could follow such a skill through `shell`, while
  delegates and restricted chats could not; and
- importing executable third-party skills is at least as sensitive as
  installing software and must require explicit user trust.

Reference: <https://github.com/skills-mcp/skills-mcp>

## Findings

### The fixed target remains correct

Every initial stdio process still runs in the one configured advanced shell through
the authenticated SSH boundary. A connection must not choose another host,
user, port, key, or SSH option. “Target” in the connection UI should therefore
mean a launchable artifact inside the advanced shell, not a machine.

### Launch and installation need different UX

AssistantMD can validate and retain an MCP launch session, but it cannot infer a
safe installation procedure from an arbitrary repository. Advanced shell is the
appropriate installation escape hatch because the user has already opted into
arbitrary advanced-shell execution. The connector should report “executable not
found” or another sanitized readiness result, not automatically install missing
software.

A future curated catalog could pair reviewed installers with launch templates,
but that is an optional product layer above the generic connector, not a
prerequisite baked into its persistence schema.

### Skills are not connection fields

A skill is agent-facing executable instruction content, not transport metadata.
It may be useful without the server, shared across connections, or coupled to a
specific provider release. Store/import it through AssistantMD's existing vault
skill model or a future reviewed skill installer. Do not place arbitrary skill
text in `mcp.db`, inject it automatically from a repository, or enable MCP
server instructions globally.

The connector may eventually expose a non-authorizing association such as
“recommended skill installed / missing / version unknown,” but connection
availability must not itself grant that skill prompt authority.

Experiment C sharpened this boundary. The pinned provider skill names bare
upstream tools such as `lsp_hover`, while AssistantMD deliberately exposes them
to the model as `<immutable-connection-slug>_lsp_hover`. Copying the upstream
file verbatim would therefore give the model inaccurate invocation names.
A reviewed AssistantMD adaptation can safely bind its prose to the immutable
connection slug, but that is authored vault content, not a path the advanced shell
connection should load.

The current default skill catalog reads only `name` and `description` from
`AssistantMD/Skills/`; extra frontmatter is parseable but no dependency field is
enforced. The initial stdio connector should therefore omit a skill path and
dependency promise. A future reviewed import flow may adapt tool prefixes and
record source commit/hash, but it must be designed as a separate feature.

### Protocol readiness is narrower than capability readiness

The pinned LSP MCP process initialized and listed all 29 tools before its
subordinate TypeScript server was usable. The first semantic call then failed
because globally installed `typescript-language-server` could not find a
TypeScript package from the mounted workspace. Installing the pinned workspace
dependencies made document-symbol and hover calls pass without changing the MCP
launch definition.

Connection **Test** can prove executable launch, MCP initialization, capability
negotiation, and catalog discovery. It cannot generically prove every
provider-specific dependency or downstream service. The UI must describe that
scope honestly and show sanitized tool-call failures during normal use rather
than label every such failure a broken connection.

### Client capabilities are part of compatibility

The prototype must inventory what FastMCP exposes for Roots, prompts, resources,
sampling, elicitation, logging, and server instructions. The first supported
contract may intentionally remain tools-only, but failures caused by an omitted
client capability must be classified as compatibility failures rather than
misreported as bad commands.

The installed FastMCP client already accepts configured Roots and exposes
sampling, elicitation, logging, progress, and message handlers. Its standard
`StdioTransport` accepts command, argv, environment, and working directory, but
spawns a process in the AssistantMD container. The future adapter can reuse its
session lifecycle around the local OpenSSH process; it must not use the standard
transport to launch the provider locally.

The live matrix negotiated MCP protocol `2025-11-25` with all three providers:

- fetch advertised tools and prompts; one tool call and prompt listing passed;
- filesystem advertised tools only, accepted `/workspace` through MCP Roots,
  exposed 14 tools, and reported `/workspace` as its effective allowed scope;
- everything advertised tools, prompts, resources, completions, logging, and
  tasks; the probe listed 13 tools, four prompts, seven resources, two resource
  templates, observed server instructions, and completed an echo call.

The probe initially called `resources/list` against fetch even though fetch had
not advertised resources, and the server correctly returned `Method not found`.
The connector must therefore branch on initialized server capabilities rather
than invoke every MCP surface speculatively. This is a compatibility rule, not a
bad-launch error.

### Structured launch needs a distinct forced-command mode

The current shell transport deliberately passes `SSH_ORIGINAL_COMMAND` to
`bash -lc`, because arbitrary shell syntax is the feature. Merely quoting a
persisted MCP executable and argv into that string would still make the shell
grammar part of the durable connection boundary.

The stdio experiment should add a versioned structured invocation marker to the
existing forced-command wrapper. AssistantMD can encode a bounded launch
envelope containing executable, argv, working directory, and permitted
environment values; the wrapper validates it and calls the provider with an
argv-based process API rather than `bash -lc`. Ordinary shell calls retain the
existing free-form mode. The model never creates the encoded envelope directly.

## Candidate Initial User Experience

This is a hypothesis to test, not yet a committed UI contract:

1. The user enables advanced mode and installs/configures a trusted provider in
   the advanced shell, either personally or by asking an advanced chat to use shell.
2. The user opens MCP Connections and selects **Advanced-shell stdio**.
3. The form identifies the advanced shell and collects a structured executable,
   ordered argument list, optional working directory, and a small allowlisted set
   of non-secret environment values.
4. **Test** launches the exact definition, performs MCP initialization, reports
   advertised capabilities, and lists the effective allowed tools. It does not
   install or repair the provider.
5. If the provider publishes a separate skill, AssistantMD links to an explicit
   review/import action. The skill remains disabled/unavailable until the user
   chooses to place trusted content in an AssistantMD vault skill location.
6. Normal chats acquire the connection through the existing retained manager;
   tools remain deferred behind tool search. Server instructions, prompts, and
   resources remain excluded unless separately designed and approved.

An alternative worth prototyping is an agent-assisted handoff: after installing
a server with shell, the agent proposes a structured launch definition for the
user to review in System. The model must not be able to activate or persist the
connection silently.

## Discovery Experiments Before Schema Work

### Experiment A: deterministic launch envelope

Status: complete for the discovery boundary. The structured argv launch,
working directory, constructed environment, bidirectional framing, normal
close, invalid-envelope failure, cancellation, and descendant cleanup are
covered by the local adversarial wrapper probe and live fixed-executable matrix.

Create a temporary, non-persisted advanced-shell stdio adapter and run the existing
fetch and filesystem servers through it. Prove:

- a versioned structured launch envelope that reaches an argv-based provider
  process without `bash -lc`;
- explicit working-directory handling;
- a minimal constructed environment rather than forwarding AssistantMD's env;
- bidirectional MCP framing over a long-lived SSH process;
- initialization/list/call/cancel/close behavior;
- bounded stderr diagnostics that cannot corrupt stdout framing; and
- process cleanup after failure, cancellation, and client invalidation.

### Experiment B: client capability matrix

Status: complete for the initial tools-oriented decision. Roots, prompts,
resources, resource templates, server instructions, and advertised capability
negotiation were observed live. Logging, elicitation, sampling, tasks, and
list-changed event behavior remain deliberately outside the first persisted
connector unless separately added to its product contract.

Use the official filesystem and everything reference servers to record behavior
for tools, Roots, prompts, resources, logging, elicitation, list-changed events,
and server instructions. Decide and document the supported subset before
persisting stdio definitions.

### Experiment C: skill-coupled provider

Status: complete. Commit
`86b05985943a7396f88d3868b72556465437bc96` (provider version `1.1.20`) and its
matching `SKILL.md` were pinned; the skill SHA-256 is
`1408ed7dc70be64ae0b2399027b59e1ba74ee93a88f29d7e5571e071cbc63632`.
TypeScript Language Server `6.0.0` and workspace TypeScript `5.9.3` were used
against `/workspace/lsp-mcp-probe-86b0598`. The provider exposed 29 documented
tools, auto-started the subordinate language server, returned document symbols
and hover data, and left no provider or language-server processes after close.

The experiment demonstrates that the tool catalog is usable without installing
the skill, while the 15 KB skill adds decision rules, canonical workflows,
gotchas, lifecycle guidance, and output-shape interpretation not captured by
individual tool descriptions. It also demonstrates that the upstream skill
requires AssistantMD-specific review/adaptation because model tool names are
connection-prefixed.

Install a pinned `lsp-mcp-server` revision and one lightweight language server
in the advanced shell against a disposable mounted workspace. Compare tool use with
and without its version-matched `SKILL.md`. Determine:

- where a reviewed skill would live in AssistantMD;
- how it can refer safely to advanced-shell paths;
- whether the existing skill discovery surface can express the dependency on
  advanced shell plus a named MCP connection; and
- what stale/missing skill status is useful without making the connection own
  prompt authority.

### Experiment D: agent-assisted installation handoff

Status: complete for the discovery question. An advanced agent cloned and
checked out the pinned provider, installed and built its dependencies, provisioned
the subordinate language server, verified versions and the skill hash, and
produced this non-persisted candidate launch definition:

```json
{
  "display_name": "LSP code intelligence",
  "executable": "/usr/local/bin/node",
  "args": [
    "/home/advanced-shell/experiments/lsp-mcp-server-86b0598/dist/index.js"
  ],
  "cwd": "/workspace/lsp-mcp-probe-86b0598",
  "env": {
    "LSP_LOG_LEVEL": "warn"
  }
}
```

No MCP database mutation was needed. This handoff is materially simpler than a
generic installer language: the agent handles arbitrary trusted setup through
shell, while the user still reviews a small deterministic connection definition
before AssistantMD persists or activates it.

Have an advanced primary chat install a pinned credential-free provider using
shell, verify its executable, and produce a candidate structured connection
definition. The only durable mutation should occur after explicit user review.
Evaluate whether this is simpler than any catalog or installer language.

## Contract Questions to Resolve

- Is argv plus working directory and bounded non-secret environment sufficient
  for the representative launch set once installation is separate?
- Do environment values belong in `mcp.db`, or should the first version omit
  them entirely to keep the credential boundary unambiguous?
- Does AssistantMD advertise MCP Roots for advanced-shell stdio servers, and if so,
  how are roots derived from explicit advanced-shell mounts rather than host paths?
- Is the retained-client lifecycle suitable for stateful providers such as a
  browser session, or does the UI need to communicate idle eviction?
- How should a user select or verify advanced-shell paths when AssistantMD cannot
  inspect them through normal file tools?
- Can existing AssistantMD vault skills express “requires advanced shell and
  MCP connection X” without a new skill persistence model?
- Should an agent be allowed to propose—but never approve—connection metadata?
- Which provider/version identity is recorded for diagnostics when the runtime
  executable itself can be replaced in persistent home?

## Persistence and Security Constraints

Any eventual schema change must keep the immutable connection ID, immutable
slug, owner principal, configuration version, lifecycle mutation protocol, and
slug tombstones. Stdio fields must be sanitized metadata only. No shell string,
private SSH setting, provider credential, or skill body belongs in the
connection row.

Executable and working-directory paths must be absolute advanced-shell paths or
resolve under an explicitly defined advanced-shell PATH. Arguments must be an array,
not one shell-evaluated command. Environment names and values, if supported,
must be length/count bounded, block transport/runtime-reserved names, and be
clearly designated non-secret. The SSH client environment remains
application-constructed.

Installation and skill import execute or authorize third-party content. Both
require explicit user intent and provenance/version visibility. Connection
testing must never mutate packages, clone repositories, run setup scripts, or
copy instructions into a vault.

## Selected Initial Connector Contract

Discovery is sufficient to select the first persisted contract. Add
`advanced_shell_stdio` as a third MCP transport. It always targets the one
deployment-configured advanced shell through the existing pinned SSH identity; no
connection field may select a host, port, SSH user, key, host-key policy, or
arbitrary SSH option.

### Persisted sanitized metadata

An advanced-shell stdio connection adds only:

- `executable`: required absolute advanced-shell path;
- `arguments`: ordered string array, including empty arguments when meaningful;
- `working_directory`: required absolute advanced-shell path;
- `environment`: optional bounded map explicitly described as non-secret; and
- `roots`: optional ordered advanced-shell absolute paths advertised as MCP file
  Roots.

The connection retains the existing immutable ID/slug, owner principal,
display name, enabled state, exact-name tool allowlist, configuration version,
mutation lifecycle, and slug tombstone. It has no URL, network-policy toggle,
auth mode choice, header, credential, OAuth configuration, installer command,
package/repository identity, skill path/body, or SSH target setting.

The initial bounds match the structured advanced-shell protocol: at most 64
arguments and 32 KiB total encoded argument content; at most 16 environment
entries with uppercase portable names and 4 KiB per value; reserved runtime
environment names cannot be overridden. Executable, working directory, and
Roots cannot contain NUL or lexical `..`. Working directory and Roots must be
under `/workspace` or `/home/advanced-shell`. Roots are persisted as paths
and converted to `file://` URIs by the client adapter.

The environment field remains necessary for representative non-secret provider
configuration such as `LSP_LOG_LEVEL`. The API/UI must call it non-secret and
must never route values into `secrets.db`. Credential-requiring providers remain
HTTP/SSE connections under the normal encrypted credential pathways.

### Database migration

Add MCP schema migration 5. Rebuild `mcp_connections` transactionally so its
transport check admits `advanced_shell_stdio`, `url` is nullable, and new sanitized
launch columns are available (`stdio_executable`, `stdio_arguments_json`,
`stdio_working_directory`, `stdio_environment_json`, and `stdio_roots_json`).
The rebuilt table must preserve every row, owner, immutable slug, timestamp,
configuration version, lifecycle state, OAuth fence, index, foreign
relationship, and slug reservation.

Database checks enforce the transport discriminator:

- HTTP/SSE rows require a non-empty URL and null stdio fields;
- advanced-shell stdio rows require a null URL, `auth_mode = 'none'`, null
  header/OAuth fields, and `allow_private_http = 0`;
- launch JSON is decoded and fully validated again in the domain service rather
  than trusted merely because it was persisted.

No secret-store mutation intent is needed for a credential-free stdio create or
update, but the existing durable metadata lifecycle and runtime invalidation
still apply. Credential/OAuth mutation methods reject advanced-shell stdio IDs.

### API contract

Extend the existing collection/item/test routes rather than creating a second
connection subsystem. Create/update/info payloads use the `transport`
discriminator. HTTP/SSE use their current URL/auth fields; `advanced_shell_stdio`
uses a nested `stdio` object containing the five launch fields above. Wrong-arm
fields are rejected rather than ignored. Responses remain sanitized and never
include owner or SSH coordinates.

Create, update, enable, and test requests for advanced-shell stdio return a stable client error
when `ASSISTANTMD_EXECUTION_MODE` is not `advanced`. Listing remains available
so a deployment switched back to restricted mode can display or delete its
durable configuration; it cannot edit, launch, or test it. A restricted runtime
treats an already-enabled stdio connection as sanitized unavailable and never
opens SSH.

The test response keeps the existing readiness shape. `ready` means the fixed
executable launched, MCP initialized,
and the effective frozen tool catalog was discovered. It does not claim that
every provider-specific downstream dependency is ready. Prompts, resources,
server instructions, sampling, elicitation, tasks, and logging are not composed
into chat by this slice.

### Runtime adapter

Move structured-envelope validation and encoding into a narrow
`core/advanced_shell` contract module. The advanced-shell forced-command decoder
retains independent fail-closed validation, with deterministic contract tests
proving the producer and decoder agree on valid and invalid envelopes.

Expose a public fixed-SSH argv builder from the advanced-shell transport rather
than having MCP call the shell executor's private method. The stdio adapter:

1. validates advanced mode and deployment key/known-host files;
2. encodes the persisted launch definition with the versioned
   `assistantmd-stdio-v1` envelope;
3. starts only the local OpenSSH client with fixed deployment coordinates;
4. keeps stdin/stdout exclusively for MCP framing;
5. discards raw provider/SSH stderr so it cannot enter model context or flood
   application logs; readiness failures remain sanitized;
6. advertises configured Roots and discovers the tool catalog; and
7. on timeout, cancellation, invalidation, idle eviction, or shutdown closes
   the SSH process so the advanced-shell wrapper reaps the complete provider tree.

The existing manager key `(principal, connection ID, config version)`, retained
client, lease count, frozen catalog, exact-name allowlist, list-changed
invalidation, idle eviction, and model-facing slug prefix remain unchanged.
One advanced-shell container may therefore host processes for multiple principals
today without claiming Linux-user isolation; a future per-principal Linux user
or per-principal advanced-shell strategy can be selected below this fixed-target
adapter without changing connection ownership or model-facing identity.

### System UI

The existing MCP add form gains **Advanced-shell stdio**. In restricted mode the
choice is visibly disabled with a short instruction to set
`ASSISTANTMD_EXECUTION_MODE=advanced` and restart. In advanced mode, selecting it
replaces URL/auth controls with:

- executable;
- working directory;
- ordered arguments (one explicit entry per item, not a shell command string);
- optional non-secret environment name/value rows; and
- optional MCP Root path rows.

The card states that the target is the deployment's advanced shell and refers
users to the advanced-shell setup instructions for installation and mounts. It
does not expose or duplicate infrastructure coordinates. Credential and OAuth
controls never render for this transport. Test results show effective tools and
explain the bounded meaning of readiness.

There is no skill picker/path in this slice. Users may independently install an
AssistantMD-reviewed skill under `AssistantMD/Skills/`; any such skill must use
the connection's immutable prefixed model tool names.

The primary creation workflow is an import box accepting strict YAML or JSON
generated by advanced chat. AssistantMD parses it into the same discriminated
request, rejects unknown fields, shows a human-readable preview, and offers
**Test and add**. The individual fields remain an expert fallback. This is one
API/runtime path, not a second registration mechanism.

A bundled `advanced_shell_mcp_setup` vault skill teaches advanced chat to install a
pinned provider, probe it with an official MCP SDK, review its tool inventory,
produce the import block, inspect any bundled provider `SKILL.md` as untrusted
content, and create a reviewed AssistantMD copy when appropriate. Provider
skills remain separate vault content and are never activated by connection
creation. Credential-free operation is the supported default; any
advanced-shell credential is explicitly user-managed rather than an
AssistantMD secret-store integration.

### Observability contract

Keep current connection events and add transport-safe decision data:

- `mcp_connection_ready`: connection ID, principal ID, transport, and tool count;
  URL only for HTTP/SSE, never launch arguments or environment values;
- existing invalidation/retry/close events include transport but no executable,
  argv, stderr, environment, SSH coordinates, or provider output.

Bounded stderr may support a sanitized error category for readiness diagnostics,
but raw lines are not activity payloads, API responses, or normal application
logs.

## Validation Targets

Planning exits into experimental feature development, not database/UI work.
The first retained artifact should be a deterministic experiment under
`validation/scenarios/experiments/` that exercises a temporary structured stdio
launch over the fixed SSH transport.

Before implementation, add or extend deterministic `integration/core`
scenarios for:

- restricted/advanced gating at mutation, test, acquisition, and chat;
- principal ownership and foreign-ID non-disclosure;
- immutable slug and configuration-version invalidation;
- exact argv/environment/working-directory validation;
- frozen allowlisted catalogs and deferred disclosure;
- cancellation, timeout, stderr noise, malformed framing, and process cleanup;
- advanced-shell unavailability without impact on HTTP MCP connections; and
- explicit exclusion of server instructions and unreviewed skill content.

The first validation slice extends the MCP persistence/API scenarios with a
advanced-shell stdio row and asserts migration preservation, conditional payload
validation, restricted-mode mutation/test denial, owner-scoped CRUD, immutable
slug, configuration-version invalidation, and credential-route rejection. It
uses a fake transport factory; no Docker or SSH belongs in the automatic core
profile.

The second slice extends manager/chat scenarios with a deterministic fake stdio
client and asserts advanced-mode acquisition, Roots propagation,
capability-aware list behavior, frozen allowlisting, prefixed deferred tools,
restricted-mode unavailability, cancellation, invalidation, idle/shutdown close,
and exclusion of instructions/prompts/resources.

The local wrapper probe remains the executable contract for envelope parsing,
literal argv, environment construction, traversal rejection, EOF cancellation,
and descendant cleanup. The live advanced-shell probes remain opt-in experiments.

Maintainers own the full integration profile. Agents run the individual new
scenario and the full Ruff/Black/MyPy production quality gate.

## Next Steps

1. Run the maintainer-owned `integration/core` validation profile.
2. Manually import, test-and-add, edit, disable, re-enable, and delete a live
   advanced-shell stdio connection through System in advanced mode.
3. Confirm restricted mode displays existing stdio metadata but blocks create,
   update, test, and runtime acquisition.
4. Perform cleanup/review and treat reviewed provider-skill import/adaptation as
   a separate future feature.
