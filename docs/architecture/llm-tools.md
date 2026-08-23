# LLM + Tools Subsystem

This subsystem builds agents, resolves model aliases, binds settings-backed tools, and composes Pydantic AI capabilities for chat, delegate, and authored direct-tool execution.

## Primary code

- `core/llm/agents.py`
- `core/llm/capabilities/`
- `core/chat/executor.py`
- `core/authoring/shared/tool_binding.py`
- `core/tools/`

Configured built-in tools include vault inspection (`file_read`), vault mutations (`file_write`), durable content ingestion (`content_import`), constrained local Python (`code_execution`), child-agent delegation (`delegate`), workflow execution (`workflow_run`), chat history compaction (`chat_history_compact`), goal tracking (`goal_ops`), session lookup and summarization (`session_ops`), and web retrieval (`web_search`, `web_extract`, `web_crawl`, and `browser`). Additional tool modules may exist under `core/tools/`, but they are available to agents only when present in the settings-backed tool registry.

## Responsibilities

- Build configured Pydantic AI agents for chat/workflow/context runs.
- Resolve model aliases through settings-backed provider/model mapping.
- Resolve tool IDs to tool classes/functions from settings through the shared tool-binding layer.
- Apply chat-mode-specific deferred approval policy without changing the
  underlying tool implementation.
- Expose concise tool definitions and virtual-doc pointers to agents.
- Compose AssistantMD-owned Pydantic AI capabilities for tool exposure, chat context, and tool result handling.
- Store oversized chat tool output in cache and return compact cache refs.
- Wrap web-derived tool results with untrusted-data boundaries.

## Chat execution flow (high level)

1. Resolve model and the registered tools not blocked by app-wide settings.
2. Build agent with AssistantMD capabilities for tool exposure, context management, and tool result handling.
3. In `inline_edit` mode, mark `file_write` calls for Pydantic AI deferred
   approval; all other enabled tools remain immediate.
4. Execute the prompt under a process-local chat task and persist
   provider-native session history.
5. Persist and publish any deferred tool request as a review artifact; an
   approved or denied review resumes through a separate queued chat task.
6. Emit tool activity metadata/events.
7. Run automatic chat history compaction when configured and recommended.

## Capability model

AssistantMD-owned Pydantic AI capabilities live under `core/llm/capabilities/`.

- `chat_context.py` wraps context-template history processing as a named capability.
- `chat_tool_output_cache.py` persists tool call/result events and routes oversized chat tool output to cache through tool lifecycle hooks.
- `assistant_tools.py` exposes settings-resolved AssistantMD tools through Pydantic AI `Toolset(FunctionToolset(...))` and applies shared tool-definition policy through `PrepareTools(...)`.
- `factory.py` composes chat capabilities for normal and streaming chat execution.
- `delegate_repeated_failure_guard.py` blocks repeated delegate child-tool calls
  that return the same structured failure with identical arguments.

These capabilities preserve the existing chat contracts while moving cross-cutting
agent behavior toward Pydantic AI's composable capability model.

## Tool loading model

- Tool registry source is settings (`tools` section in settings store).
- Tool availability is the registered tool set minus the app-wide
  `disabled_tools` list. Chat has no per-session or per-turn tool selector.
- `resolve_tool_binding(...)` imports configured modules and finds `BaseTool` subclasses.
- Chat, delegate child agents, and authored direct-tool calls attach tools through `core/llm/capabilities/assistant_tools.py`.
- Pydantic AI model providers are constructed with retry-enabled HTTP clients using `pydantic_ai.retries.AsyncTenacityTransport` and `wait_retry_after(...)`. The transport retries provider rate limits, provider 5xx responses, and network request errors with bounded attempts; permanent 4xx responses are left for provider/model error handling. Tool execution is not automatically retried by infrastructure; tool failures should return structured, model-visible failure metadata so the model can decide the next action.
- OpenAI provider construction goes through `core/llm/openai_runtime.py`, which resolves API-key versus experimental OAuth auth mode before creating the Pydantic AI provider. OAuth runtime construction is behind an explicit adapter boundary; without an adapter, OAuth mode fails clearly instead of treating OAuth tokens as API keys.
- Tool result caching is handled by chat capabilities rather than tool-call routing parameters.
- Oversized chat tool output is stored through the authoring cache layer, not the legacy in-memory buffer store.
- `BufferStore` remains available on `RunContext.deps` for tool compatibility; the deprecated typed output-routing modules that wrote variable-style buffers have been removed.

## Web Capability Strategies

`web_search`, `web_extract`, and `web_crawl` are stable model-facing
capabilities. Their provider implementations are selected independently through
the string settings `web_search_strategy`, `web_extract_strategy`, and
`web_crawl_strategy`.

Strategy resolution, provider secrets, normalized results, URL policy, and
provider calls live under `core/web/`. Tool modules only validate
capability-level arguments, format normalized results, and translate failures
into structured tool returns. A selected strategy is authoritative: the web
service does not silently invoke a different provider or launch `browser` after
a failure.

`web_extract` returns transient content for agent reasoning. URL ingestion may
reuse the same bounded curl transport and HTML-to-Markdown converter, but it
retains its own durable jobs, rendering, storage, and vault-mutation policy.

`browser` is an explicit Chromium capability for dynamic pages. It has a
process-wide session semaphore, a per-execution-task call budget, and cgroup
memory admission checks. Browser logs include process and cgroup memory context
where available and sanitize URL credentials, query strings, and fragments.

## Vault File Tools and Inline Review

`file_read` and `file_write` are thin model-facing adapters over
`core.vault_state.file_operations`. The operation service owns path validation,
text behavior, and stable rejection metadata. Mutating operations then route
through `core.vault_state.file_mutations` for locking, snapshots, attribution,
manifest refresh, and rollback support.

`file_read` supports `read`, `list`, `search`, and `frontmatter`. `file_write`
supports `write`, `append`, `edit_line`, `replace_text`, `move`, `delete`, and
`mkdir`. `write` is create-only unless `overwrite=true`; deletion requires an
exact `confirm_path`.

Chat mode controls review policy at capability preparation time:

- `normal` executes enabled tools normally.
- `inline_edit` defers each `file_write` call through Pydantic AI approval and
  leaves `file_read` immediate.

Review decisions are structured deferred-tool results. The browser never
constructs prompts to describe approval. Approved calls may override only the
editable content or destination fields allowed by the backend; they cannot
change the operation target or overwrite policy. Existing-file overwrite,
move, and delete approvals also validate the reviewed target's existence and
content hash before a continuation task is accepted. A denial can include a
user reason, which is returned to the model in the `ToolDenied` result.

Workflows, context scripts, code execution, and delegate agents do not have an
interactive user-review channel. Their enabled tool calls execute directly.

## OpenAI Auth Modes

The built-in `openai` provider supports two auth modes:

- `api_key`: the stable default. Runtime requests use the configured OpenAI API
  key secret or compatible endpoint configuration.
- `oauth`: an experimental Codex/ChatGPT-compatible OAuth path. It is available
  only when the global `openai_oauth_enabled` setting is true and an OAuth token
  is connected.

OpenAI OAuth state is owned by `core/llm/openai_oauth.py`. Pending auth attempts
and connected token state are stored as internal secrets, hidden from the
generic Secrets UI/API, and exposed only through sanitized provider status
fields. OAuth supports both PKCE callback/manual completion and device-code
completion for remote deployments.

Runtime auth resolution is centralized in `core/llm/openai_auth.py` and
`core/llm/openai_runtime.py`. The global OAuth disable setting is authoritative:
when disabled, OpenAI resolves as API-key-only even if OAuth token state exists.
API-key fallback from OAuth mode is opt-in through
`oauth_api_key_fallback_enabled`, so the runtime does not silently switch billing
paths. If OAuth is selected but unavailable and fallback is not enabled, model
construction fails with actionable reconnect/switch-auth guidance.

## Delegate and Code Execution

`delegate` creates a bounded child agent with an isolated prompt, optional model
alias, optional tool list, and internal request, tool-call, repeated-failure,
and timeout guardrails. Every child receives a compact system-owned flight card
and its effective tool-call budget. Completed and bounded-failure returns include
compact audit metadata summarizing child tool calls, return previews, and tool
errors. Failures include structured classification, usage, and the latest
bounded partial output, an audit that distinguishes settled from unsettled
calls, and cache/artifact references available in process. Delegate progress is
not persisted and child tools are never replayed
to construct a failure handoff.

Primary chat attaches a task-scoped Harness `StepPersistence` capability. Its
bounded in-memory snapshots preserve settled model/tool boundaries during the
live execution task. A transient disconnect can continue after completed tool
calls without re-executing them. Unsettled replay-safe tools may run again;
unsettled vault mutations require terminal task rollback before one replacement
task starts; unknown or external effects fail closed for manual recovery.
Recovery state does not survive a process or container restart. Delegate runs
currently apply automatic retry only while no child tool effect has occurred.

`code_execution` runs constrained Monty Python in the active chat session. It shares the authoring runtime and helper/tool surface used by workflow and context scripts, but is exposed as a normal chat tool.

`workflow_run` delegates workflow execution to `RuntimeContext.workflow_governor`, so tool-triggered runs use the same vault-level execution lane and task lifecycle policy as API, system-template, and scheduled runs. Its blocking `run` operation waits for completion. Its asynchronous `start`, `status`, and `cancel` operations expose the same process-local workflow task records used by the UI, including heartbeat/progress metadata when available. `run` and `start` can resolve an explicit vault-relative Markdown workflow outside managed discovery. The resolver requires real-path containment, a `.md` file, and explicit `run_type: workflow`; path-based runs do not enter workflow discovery, scheduling, or lifecycle management.

`chat_history_compact` checks or compacts the active chat session after explicit user approval. Compaction records a replay checkpoint so default future history starts with a summary plus recent raw messages, and records a process-local history-compaction task.

`goal_ops` records lightweight durable goal state for longer work. It stores
status, source provenance, compact plan snapshots, checkpoints, and related
activity derived from existing vault mutation records. It does not execute work
or create a separate artifact pathway.
