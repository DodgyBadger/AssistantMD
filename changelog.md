# Changelog

## 2025-11-07 - Improve UI configuration and chat experience

Implemented full secrets CRUD with provider pointer semantics plus inline tool streaming and manual scroll control in chat.

---

## 2025-11-07 - Complete directive documentation

Added missing @run-on and @header directives to core-directives.md documentation

---

## 2025-11-01 - Simplified model unavailability messages

Changed model unavailability message from verbose "Model X unavailable until secret Y is configured" to concise "Configure Y" since the Unavailable badge already provides context

---

## 2025-11-01 - Configuration UI Redesign

Rebuilt Configuration tab with responsive card-based layout:
- Fixed layout issues: cards no longer stretch infinitely on wide screens, badges constrained with `w-fit`, consistent horizontal alignment
- Improved visual design: softer badges with rings, removed uppercase labels, larger buttons, subtle edit state highlighting
- Simplified UI: removed redundant badges and buttons (provider Update/Clear buttons, built-in provider badge, hot reload badges)
- Consistent patterns: status badges next to labels in Secrets and Providers, availability under model name
- Better spacing: increased padding, hover effects, improved mobile responsiveness

---

## 2025-10-31 - Persist empty secrets

**Secrets management:** Keeping all template keys intact when editing secrets.yaml; blank entries now stay in place and serialize correctly.

---

## 2025-10-31 - Disable tools without secrets

**UI fix:** Chat tool checkboxes now respect configuration availability, so Tavily and other secret-backed tools stay disabled until their keys are set.

---

## 2025-10-31 - Fix secrets ordering in UI

**Secrets management:** Preserve secrets.yaml order (including blank entries) and surface all keys in the configuration UI.

---

## 2025-10-31 - Relax UID/GID override defaults

**Container orchestration:** docker-compose override now falls back to UID/GID 1000 if host values are not provided, with docs updated accordingly.

---

## 2025-10-31 - Seed secrets from template

**Secrets management:** Added template-backed seeding for system/secrets.yaml and removed committed sample secrets.

---

## 2025-10-31 - Remove legacy vault path warning

**UI cleanup:** Dropped the VAULTS_ROOT_PATH warning since vault mounts are managed via docker compose.

---

## 2025-10-31 - Fix pydantic-ai import error

**Dependency update:** Raised pydantic-ai to >=1.6.0 so streaming imports are available in production runtime.

---

## 2025-10-30 - Improve chat streaming experience

- Disabled compression on SSE responses to keep Chrome streaming.\n- Simplified chat UI status indicators and redesigned tool call details.\n- Dropped redundant FILES_CREATED_OR_MODIFIED instruction for file ops tool.

---

## 2025-10-29 - Backend: Fix streaming to support tools

Fixed streaming implementation to use run_stream_events() instead of run_stream() for proper tool call handling. Updated event type imports and attributes (tool_call_id instead of function_name). Backend now correctly streams text deltas and tool execution metadata.

---

## 2025-10-27 - Web tool token limit protection

Added configurable token limit for web extraction tools (`tavily_extract`, `tavily_crawl`) to prevent context window overflow. Tools now reject extractions exceeding the limit (default 50K tokens) with actionable error messages. Limit is configurable via `web_tool_max_tokens` setting in `system/settings.yaml`. Created reusable `estimate_token_count()` utility in `core/tools/utils.py` using tiktoken.

---

## 2025-10-27 - Expand tool validation coverage

## Highlights
- Added integration/tool_suite scenario to exercise every AssistantMD tool with TestModel
- Hardened Tavily tools to return readable errors and default to conservative settings
- Updated documentation and crawl instructions to stage large fetches in multiple passes

---

## 2025-10-27 - Streamline Docker runtime setup

## Highlights
- Docker image now runs as built-in appuser without entrypoint shim
- Simplified docker-compose template and added override example for UID/GID customization
- Updated setup docs to match new compose flow and override usage

---

## 2025-10-26 - Refine secrets and container runtime

**Secrets & validation polish**
- Missing LLM keys now warn instead of aborting runtime bootstrap
- Validation harness reuses production secrets store, writes run artifacts under /system, and exercises the /api/system/secrets endpoint
- Docker entrypoint aligns runtime APP_UID/APP_GID and docs/compose guide users on host mount ownership

---

## 2025-10-26 - refactor: migrate configuration to secrets store

**Major configuration refactor**
- replaced .env-based secret handling with YAML-backed secrets store (`core/settings/secrets_store.py`) that now powers models, tools, and logging (`core/directives/model.py`, `core/llm/model_utils.py`, `core/logger.py`)
- introduced secrets CRUD API/endpoints and UI updates so Configuration tab manages secrets directly (`api/endpoints.py`, `api/services.py`, `static/index.html`, `static/js/configuration.js`)
- decommissioned env_store and old validation env loaders; validation now overlays run-local secrets atop shared validation/system secrets (`validation/core/system_controller.py`)
- updated docker/docs to move infrastructure vars into compose and document new secrets workflow (`docker-compose.yml.example`, `docs/setup/installation.md`, `docs/setup/configuration.md`, `docs/security.md`)
- ensured tools/providers require secrets metadata via settings templates and runtime validation (`core/settings/settings.template.yaml`, `system/settings.yaml`)
- broad codebase sweep swapping os.getenv() usage for secrets lookups and settings YAML reads, including agent defaults, Tavily tools, and api utils.

---

## 2025-10-26 - refactor: align validation validation harness

Aligned validation harness with the production FastAPI app.
- Boot FastAPI TestClient during validation runtime startup and reuse across scenarios
- Added integration/api_endpoints scenario covering health, config, execution, and chat endpoints
- Removed deprecated interactive prompt endpoint and related helpers
- Isolated validation .env mutations to run-local files and refreshed docs

---

## 2025-10-25 - UI: Settings and environment variables display in file order

Configuration tab now displays settings and environment variables in the order they appear in settings.yaml and .env files respectively, instead of alphabetically sorted. This preserves intentional organization.

---

## 2025-10-25 - UI: Improved chat message styling

Chat messages now use pale blue background for LLM responses and gray for user messages (swapped from previous bright blue user messages). Disabled tool labels changed from red to muted gray for less visual alarm.

---

## 2025-10-25 - Validation: Self-contained scenario templates

Scenarios now use inline template constants (e.g., `HAIKU_WRITER_ASSISTANT`) defined at the bottom of each file instead of separate template files. This makes scenarios self-contained and easier to read without jumping between files. The `copy_files()` method remains available for shared templates.

---

## 2025-10-25 - Validation: Folder-based scenario organization

Scenarios can now be organized into subdirectories for better categorization (e.g., `scenarios/integration/`, `scenarios/experiments/`). Run entire folders or individual scenarios: `python validation/run_validation.py run integration` expands to all scenarios in that folder. Backward compatible with flat structure.

---

## 2025-10-25 - Configuration consolidation (Phase 3.5-3.6)

- Migrate configuration to  with typed loader and general settings metadata.
- Update API/CLI/validation paths to use new settings store; drop legacy mappings loader.
- Refresh configuration UI to edit models, providers, general settings, and .env dynamically.

---

## 2025-10-24 - Configuration management overhaul (Phase 1-3)

**Introduced typed configuration handling with clear user feedback**\n- Centralized settings in core/settings with validation and tool/provider metadata.\n- Validated configuration health at bootstrap and surfaced availability through status APIs for safe degradation.\n- Added guided mappings/.env editors, runtime reload service, and persistent restart warnings across configuration and chat UIs.

---

## 2025-10-23 - OpenAI-Compatible Endpoints and Provider Config Refactor

Major refactor of provider configuration system to support unlimited custom OpenAI-compatible endpoints (Ollama, LM Studio, vLLM, etc.).

**What Changed**:

**Provider Configuration**:
- Provider config loading now returns full provider configurations generically (any key/value pairs)
- Any provider not explicitly recognized (google, anthropic, openai, mistral) automatically treated as OpenAI-compatible
- Users can configure unlimited custom providers in `system/mappings.yaml` with any provider name
- Both `api_key` and `base_url` use consistent env var pattern: set env var name in mappings, actual value in `.env`

**Test Model**:
- Test model now hardcoded in `ModelDirective` (removed from mappings.yaml)
- Prevents accidental deletion breaking validation scenarios
- Test model is system infrastructure, not user configuration

**Configuration Example**:
```yaml
# system/mappings.yaml
providers:
  ollama:
    api_key: null
    base_url: OLLAMA_BASE_URL
  lmstudio:
    api_key: null
    base_url: LMSTUDIO_BASE_URL

models:
  llama:
    provider: ollama
    model_string: llama3.2
  qwen:
    provider: lmstudio
    model_string: qwen2.5
```

```bash
# .env
OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
LMSTUDIO_BASE_URL=http://host.docker.internal:1234/v1
```

**Breaking Changes**:
- Removed `PROVIDER_API_KEYS` dict - use `get_provider_config(provider)` instead
- Custom providers require `base_url` configured in mappings.yaml (fails with clear error if missing)
- Test model and provider removed from mappings.yaml template

**Files Modified**:
- `core/llm/model_utils.py`: Generic provider config loading with `get_provider_config()`
- `core/directives/model.py`: Fallback to OpenAI-compatible for unrecognized providers, hardcoded test model
- `core/mappings.template.yaml`: Ollama and LM Studio examples, test entries removed
- `.env.example`: Local model endpoint configuration examples

---

## 2025-10-23 - Multiple OpenAI-Compatible Endpoint Support

Refactored provider configuration to support multiple custom OpenAI-compatible endpoints (Ollama, LM Studio, vLLM, etc.).

**What Changed**:
- Provider config loading now returns full provider configurations generically
- Any provider not explicitly recognized (google, anthropic, openai, mistral, test) is treated as OpenAI-compatible
- Users can configure unlimited custom providers in `system/mappings.yaml`
- Both `api_key` and `base_url` follow the same pattern: set to env var name in mappings, configure actual values in `.env`

**Configuration Pattern**:
```yaml
providers:
  ollama:
    api_key: null
    base_url: OLLAMA_BASE_URL
  lmstudio:
    api_key: null
    base_url: LMSTUDIO_BASE_URL

models:
  llama:
    provider: ollama
    model_string: llama3.2
  qwen:
    provider: lmstudio
    model_string: qwen2.5
```

**Breaking Changes**:
- Removed `PROVIDER_API_KEYS` dict - use `get_provider_config(provider)` instead
- Custom providers now require `base_url` configured in mappings.yaml (fails with clear error if missing)

**Implementation**: 
- `core/llm/model_utils.py`: Generic provider config loading
- `core/directives/model.py`: Fallback to OpenAI-compatible for unknown providers
- `core/mappings.template.yaml`: Examples for ollama and lmstudio
- `.env.example`: Added OLLAMA_BASE_URL and LMSTUDIO_BASE_URL examples

---

## 2025-10-23 - Frontmatter Quote Resilience

Frontmatter parser now handles both quoted and unquoted values seamlessly.

**What Changed**:
- Parser automatically strips outer quotes (both single and double) from all frontmatter values
- Works with both Obsidian's auto-quoted format (`schedule: "cron: 0 8 * * *"`) and manual unquoted format (`schedule: cron: 0 8 * * *`)
- Applies to all fields: `schedule`, `description`, `workflow`, etc.

**Why This Matters**:
- Obsidian automatically adds quotes around values with special characters
- Users editing raw markdown may not use quotes
- Both formats now work identically without any special handling required

**Implementation**: Added quote stripping logic in `core/assistant/parser.py` (lines 131-134) that removes matching outer quotes while preserving quotes that are part of the actual content.

---

## 2025-10-22 - Schedule Syntax Migration

**Breaking Change**: Migrated from custom schedule syntax to standard crontab format with explicit type prefixes.

**Old Syntax** (no longer supported):
- `schedule: every 1d at 8am`
- `schedule: every 30m from 9am to 5pm`
- `schedule: once on 2025-12-25 at 10am`

**New Syntax**:
- `schedule: cron: 0 8 * * *` (daily at 8am)
- `schedule: cron: */30 9-17 * * *` (every 30 min, 9am-5pm)
- `schedule: once: 2025-12-25 10:00` (one-time, explicit datetime)

**Key Changes**:
- All recurring schedules now use standard crontab syntax with `cron:` prefix
- One-time schedules use explicit datetime with `once:` prefix (no relative terms like "tomorrow")
- No quotes needed in frontmatter (custom parser handles colons)
- Error messages guide users to correct syntax with link to https://crontab.guru

**Implementation Details**:
- Replaced YAML frontmatter parser with custom key-value parser (eliminates syntax restrictions)
- Removed ~240 lines of custom schedule parsing code
- Removed deprecated IntervalTrigger support
- Added `schedule_string` field to Assistant model for display
- API now returns original schedule syntax exactly as written

**Rationale**: Standard crontab syntax prevents LLM hallucination of unsupported schedule features, is well-documented, and user-verifiable via online tools.

---

## 2025-10-22 - Assistant Subfolder Organization Support

**Assistant Organization**
- Assistants can now be organized into subfolders within the `assistants/` directory (one level deep)
- Folders prefixed with underscore (e.g., `_chat-sessions`) are automatically ignored during discovery
- Global IDs include subfolder in the name (e.g., `vault/planning/daily` for `assistants/planning/daily.md`)
- Scheduler job IDs correctly handle subfolder paths with double-underscore separator

**Chat History Organization**
- Chat session history files moved from `assistants/chat-sessions/` to `assistants/_chat-sessions/`
- Underscore prefix ensures chat history folder is excluded from assistant discovery

**Validation**
- Enhanced `system_startup_validation` scenario to test subfolder assistant discovery, loading, and persistence
- Added `quick_job_2.md` template for subfolder testing

---

## 2025-10-21 - Configuration tab exposes system log and mappings editor

Added a configuration tab with an activity log viewer and editable mappings.yaml (validated with the backend) plus moved mappings to /app/system for persistence and switched the frontend to local marked.js.

---

## 2025-10-20 - SQLAlchemy instrumentation

Added Logfire SQLAlchemy instrumentation support (commented out by default to reduce trace noise). Can be enabled in `core/logger.py` for detailed database query debugging when needed.

---

## 2025-10-20 - Collapse barrel imports and harden validation CLI

- Removed lazy __getattr__ exports across core packages; callers now import concrete modules.
- Flattened logger module to core/logger.py and introduced validation.env helper.
- Tightened validation runner CLI to require explicit scenarios and optional --dev env overrides.

---

## 2025-10-20 - Lazy import loaders for circular dependency hotfix

Introduced lazy export loaders in `core/runtime/__init__.py` and `core/llm/__init__.py` using `__getattr__` shims. These defer heavy imports until first use, eliminating the circular import crash that blocked uvicorn startup in production. This is a temporary bandaid - see `project-docs/2025-10-21 - runtime-init-cleanup/summary.md` for planned cleanup to remove barrel imports entirely.

---

## 2025-10-19 - Prompt injection security validation and mitigation

Added comprehensive prompt injection testing framework and security mitigations:
- Created validation scenario testing 6 injection vectors (hidden CSS, JSON-LD, meta tags, noscript/comments, unicode/a11y, multi-page crawl)
- Added `WEB_TOOL_SECURITY_NOTICE` constant with defensive instructions for all web-facing tools
- Applied security notice to `tavily_extract`, `tavily_crawl`, `web_search_duckduckgo`, and `web_search_tavily`
- Consolidated all LLM prompts from `core/llm/prompts.py` into `core/constants.py` for better organization
- Documented security considerations in new `docs/security.md` 
- Added security warning to `docs/core/core-directives.md` for `@tools` directive
- Testing confirms mitigation is effective: mistral-small now detects and resists injection attempts that previously succeeded

---

## 2025-10-17 - UI: Add Tailwind CSS build pipeline with typography plugin

* Added Node.js build stage to Dockerfile for compiling Tailwind CSS during image build
* Installed @tailwindcss/typography plugin for automatic markdown styling in chat interface
* Replaced CDN script with compiled output.css to eliminate production warnings
* Created tailwind.config.js, package.json, and static/input.css for build configuration
* Updated chat interface to use typography plugin's `prose` classes instead of custom CSS
* Removed 60+ lines of custom markdown styling in favor of typography plugin

**Multi-line chat input improvements:**
* Made message textarea vertically resizable with corner drag handle
* Changed submit from Enter to Ctrl+Enter/Cmd+Enter for multi-line support
* Line breaks now preserved in user messages with proper HTML escaping
* Removed unused chat.html and chat.js files

**Known Issue:**
* In development mode with /app volume mount, output.css is overwritten by host directory
* Workaround: Run `npm install && npm run build:css` on host, or use anonymous volume
* Will be resolved when publishing production Docker image to GHCR (no volume mount)

---

## 2025-10-17 - Streamline architecture docs and validation harness

* Replaced the architecture overview with a concise module-first quick reference and refreshed the validation framework guide for the V2 scenario API.
* Hardened validation helpers by restoring lazy imports, tolerating optional psutil diagnostics, and documenting scheduler timing trade-offs.
* Verified scenario coverage with `basic_haiku` and `chat_basic`, and updated the review matrix notes for the scheduler database helper.

---

## 2025-10-17 - Create review matrix tooling and cleanup automation

* Added review-matrix utilities under `scripts/` to generate the CSV, populate lint status, and surface in-function imports.
* Ran the new commands to refresh `project-docs/review-matrix.csv`, clearing lint warnings and documenting any deliberate lazy imports.

---

## 2025-10-14 - UI: Chat interface enhancements including markdown rendering improvements and prompt organization

--type

---

## 2025-10-13 - feat: Add required parameter to @input-file and improve {pending} pattern reliability

The @input-file directive now supports an optional required parameter for conditional step execution, and the {pending} pattern uses content hashing for robust file tracking.

**@input-file Required Parameter:**
- Syntax: @input-file path/to/files (required) or (required=true)
- When specified, workflow steps are skipped if no matching files are found
- Skipping happens before the LLM prompt is built, saving API costs and execution time
- Works with all pattern types: direct files, glob patterns, time-based patterns ({latest:3}), and stateful patterns ({pending})
- Example use case: Weekly invoice generator that only runs when unprocessed timesheets exist

**{pending} Pattern Improvements:**
- Now uses SHA256 content hashing instead of file paths for tracking processed files
- Renaming or moving files does not mark them as unprocessed (robust to refactoring)
- Editing file content marks files as unprocessed (ensures changes are re-processed)
- Eliminates path format issues (relative vs absolute, with/without extensions)
- State tracking remains per-assistant and per-pattern for proper isolation

**System Database Isolation:**
- System databases (file_state.db) now properly isolated in validation scenarios
- Uses runtime context pattern for consistent path resolution across all components
- Validation runs no longer share state, ensuring test independence

---

## 2025-10-12 - Fix rescan to remove jobs for disabled assistants

Fixed bug where disabling an assistant and rescanning would not remove its job from the scheduler. Now `setup_scheduler_jobs` properly removes orphaned jobs by comparing scheduler jobs against enabled assistants, ensuring disabled assistants stop running.

---

## 2025-10-12 - Fix interval schedules to honor time specification for all interval types

Fixed bug where `every 4w at 9am`, `every 2h at 10am`, and other non-daily intervals ignored the time specification. Now all interval types (minutes, hours, days, weeks) properly set `start_date` when `at` time is specified, ensuring schedules run at the correct time.

---

## 2025-10-12 - Enable Pydantic AI retry functionality for tool validation errors

Added `DEFAULT_TOOL_RETRIES` constant (default: 3) and `retries` parameter to `create_agent()` function. When models submit incorrect tool parameters, Pydantic AI now automatically retries up to 3 times with error feedback, helping smaller models like gemini-flash that frequently make tool validation errors.

---

## 2025-10-11 - Replace Marimo interface with custom HTML/JS web UI

Replace Marimo notebook interface with custom HTML/JavaScript chat UI served by FastAPI. Built two-tab interface (Chat + Dashboard) with collapsible sections and improved UX.

**Key Changes:**
- Add /app/static/index.html and /app/static/app.js for custom web interface
- Update main.py to serve static files and add /app.js route with explicit MIME type
- Fix tool name conflicts in web_search_tavily and web_search_duckduckgo
- Remove marimo folder and all notebook files
- Update docs/setup/installation.md to reference new web interface
- Add session metadata display and loading animations for better UX
- Consolidate Mode, History, and Tools into single "Advanced" section

**Benefits:**
- Interactive chat with vault/model/tool configuration
- Dashboard with system metrics, scheduled jobs, and manual execution
- Better compatibility with reverse proxy environments using relative paths
- Cleaner, more maintainable codebase without Marimo dependency

---

## 2025-10-10 - Autonomous Agent Validation Scenario

Created validation scenario demonstrating autonomous agent capabilities using file operations tools. Agent successfully breaks down goals, creates task plans, and manages multi-file outputs without explicit directives.

---

## 2025-10-10 - Fixed Logfire Token Loading in Validation

Fixed environment variable loading order to ensure LOGFIRE_TOKEN is available before Logfire configuration. Moved env loading to validation package __init__.py for proper initialization sequence.

---

## 2025-10-10 - Usage Examples Documentation

Added comprehensive usage examples documentation showing the spectrum from explicit workflows to autonomous agents. Includes tips and best practices for different automation patterns.

---

## 2025-10-09 - Make @output-file optional in step workflows

Changed @output-file from required to optional directive, enabling more flexible workflow patterns.

**Changes:**
- @output-file is now optional in step workflows
- Steps without @output-file execute for side effects only (tool calls, analysis, etc.)
- State manager still updates for pending patterns even without output file

**Use Cases Enabled:**
- **Pure tool-based workflows**: Omit @output-file and use file_ops tools to manage all file creation
- **Analysis steps**: Read and analyze files without creating output
- **Side-effect steps**: Execute operations without writing LLM response to a file

**Best Practice Guidance:**
- Choose one approach per step: explicit outputs (@output-file) OR tool-managed outputs (file_ops)
- Avoid mixing both in the same step to prevent unpredictable file creation
- Explicit @output-file recommended for most workflows for predictability

**Documentation:**
- Updated core-directives.md with best practice guidance
- Clarified when to use each approach
- Warning about mixing @output-file with file_ops write operations

---

## 2025-10-09 - File Operations Tool Restructure

Restructured file operations tools into safe and unsafe variants for better security and intentionality.

**Breaking Changes:**
- Renamed `file_operations` → `file_ops_safe` (clean break, no backward compatibility)
- Tool name changes require updating `@tools` directives in assistant files

**New Features:**
- **file_ops_safe**: Safe operations only (read, write new, append, list, search, mkdir, move to new destination)
- **file_ops_unsafe**: Unsafe operations with explicit opt-in (edit_line, delete, replace_text, move_overwrite, truncate)
- Shared path validation utility (`core/tools/utils.py`) ensures both tools enforce vault boundaries
- file_ops_unsafe requires file_ops_safe for read operations - LLM will notify user if not enabled

**Security:**
- Unsafe operations require explicit confirmation parameters (e.g., delete requires confirm_path)
- Edit operations require exact old_content match to prevent accidental changes
- Unsafe tool intentionally excluded from user documentation to prevent casual LLM suggestions
- All operations maintain vault boundary enforcement and .md extension requirements

**Validation:**
- Extended file_operations_test scenario with STEP3 testing unsafe operations
- Confirmed edit_line and replace_text working correctly
- Template creation and modification validated

---

## 2025-10-09 - Phase 5 & Dynamic Prompt Execution Complete (5)

Completed Phase 5 (Streaming Support) and entire Dynamic Prompt Execution feature implementation.

Phase 5: Streaming Response Support
- Implemented OpenAI-compatible streaming API with single unified endpoint
- Added DRY helper function to eliminate code duplication between streaming/non-streaming
- Stream parameter (stream: bool) controls response format
- Session ID returned in X-Session-ID header for streaming
- API cleanup: renamed endpoints, removed redundant clear-history endpoint
- Marimo UI works with non-streaming (mo.ui.chat limitation), streaming ready for other clients

Overall Feature Status
All phases of Dynamic Prompt Execution now complete:
- Phase 1: Chat Execution Core
- Phase 2: Marimo Dashboard Integration
- Phase 2.4: Human-Readable Session IDs
- Phase 2.5: History Management & UI Refinements
- Phase 3: LLM-Powered Assistant Creation
- Phase 3.5: UI-Driven Session Mode Management
- Phase 5: Streaming Response Support

The system now provides a complete chat interface for interactive AI conversations with vault context, tool access, conversation history management, assistant creation workflows, and OpenAI-compatible streaming API.

---

## 2025-10-06 - Phase 3.5: UI-driven session mode management (Phase 3.5)

Implemented session mode selection via UI dropdown, enabling different chat modes (regular, assistant creation) without backend metadata storage. Added Mode dropdown to chat interface and refactored instruction composition for consistency across workflows.

---

## 2025-10-05 - Phase 3: LLM-Powered Assistant Creation (Phase 3)

**Backend Implementation:**
- Created `core/llm/prompts.py` for centralized LLM prompt templates
- Added `generate_session_id()` utility in `api/utils.py` for consistent session ID generation
- Renamed `CompactHistoryRequest/Response` to `ChatSessionTransformRequest/Response` for generic use
- Implemented `start_assistant_creation()` service function supporting both fresh start and existing conversation scenarios
- Added `POST /api/chat/create-assistant` endpoint

**UI Implementation:**
- Added "✨ Create Assistant" button to Marimo chat interface
- Auto-enables `file_operations` and `documentation_access` tools when clicked
- Switches to new creation session automatically

**Documentation Restructure:**
- Created `docs/workflows/step-template.md` - Complete, valid assistant file with zero commentary
- Updated `docs/assistant-setup.md` to template-first approach
- LLM now sees concrete example immediately, explores details only if needed

**Testing:**
- Unit tests passing for session ID generation, prompts module, and API models
- Documentation testing with subagent proves LLM can create valid assistants from plain language requests
- Integration testing and validation scenarios pending

**Key Design:**
- Maximum code reuse (~90% existing code)
- Follows exact pattern of `compact_conversation_history()`
- LLM asks user-friendly questions, translates to technical configuration
- Defense in depth: UI auto-enables tools + LLM instructions check for tools

---

## 2025-10-01 - Phase 1: Chat Execution Core Complete (Phase 1)

**Chat Execution System**
- Added chat execution with stateful/stateless conversation modes
- Created `/api/chat/execute` endpoint with user-selected tools and models
- Created `/api/chat/metadata` endpoint for dynamic UI configuration
- Implemented session manager for conversation history tracking
- Added chat history persistence to `{vault}/assistants/chat-sessions/{session_id}.md`

**Infrastructure Improvements**
- Created shared `core/mappings_loader.py` to eliminate code duplication
- Refactored `model_utils.py` and `tools.py` to use shared mappings loader
- Implemented injectable `vault_path` parameter for validation framework compatibility

**Validation Framework**
- Created `chat_execution_service.py` for isolated test execution
- Added `run_chat_prompt()` method to `BaseScenario` for high-level chat testing
- Added chat transcript assertions for verifying saved history
- Created `chat_basic.py` validation scenario with real model execution

**API Models**
- Added `ChatExecuteRequest`, `ChatExecuteResponse`, `ChatMetadataResponse`
- Added `ModelInfo` and `ToolInfo` for dynamic configuration

**Bug Fixes**
- Fixed tools directive to use injected `vault_path` instead of hardcoded paths

All features implemented, tested, and validated. Ready for Phase 2: Marimo Dashboard Integration.

---

## 2025-09-23 - test: add documentation learning scenarios

Added documentation-focused validation templates and scenarios plus doc hyperlink updates; ran experiments revealing docs insufficient for LLM-driven assistant authoring.

---

## 2025-09-23 - Refactor scheduler worker config

Introduced DEFAULT_MAX_SCHEDULER_WORKERS constant and wired RuntimeConfig defaults to it for easier experimentation.

---

## 2025-09-23 - Refactor step workflow logging

Initialized workflow step tracking before logging to avoid masking upstream errors and removed unused helper parameter.

---

## 2025-09-21 - Add automatic cleanup to validation framework

- Added automatic cleanup of old validation runs before executing scenarios
- Keeps 9 existing runs + 1 new run = 10 total runs maximum
- Uses timestamp parsing from directory names (YYYYMMDD_HHMMSS_scenarioname format)
- Graceful error handling with warning messages for cleanup failures
- Prevents validation/runs directory from growing indefinitely
- Eliminates need for manual cleanup of old validation artifacts

---

## 2025-09-21 - Split tool backends and remove MCP Python dependency

- Split web search tools into separate DuckDuckGo and Tavily implementations
- Split code execution into LibreChat-only implementation (removed MCP Python)
- Updated tool mappings with named backends and generic aliases
- Removed Deno dependency from Docker container (cleaner, faster builds)
- Updated validation framework with comprehensive multi-tool scenario
- Generic aliases: web_search → DuckDuckGo (free), code_execution → LibreChat (premium)
- Custom tool implementations replace pydantic-ai wrappers for better control

---

## 2025-09-20 - Runtime Bootstrap Refactor

**Major architectural refactor to unify bootstrap and eliminate global singletons**

- **Unified Bootstrap**: Created `core/runtime/` package with `RuntimeConfig`, `RuntimeContext`, and `bootstrap_runtime()` for centralized service initialization
- **Eliminated Global State**: Removed global `assistant_loader` singleton and enforced runtime context as single source of truth  
- **Refactored main.py**: Converted FastAPI lifespan to use runtime bootstrap with proper context lifecycle management
- **Updated API Layer**: Removed `from main import scheduler` dependencies, APIs now use runtime context for service access
- **Aligned Validation Framework**: Validation now uses identical bootstrap path as production, eliminating code duplication
- **Fixed Context Lifecycle**: Runtime context properly cleared on shutdown to support multiple startup/shutdown cycles
- **Enhanced Error Handling**: Clear error messages when runtime context unavailable, fail-fast design prevents architectural violations
- **Improved Test Isolation**: Each test gets clean runtime context with explicit teardown via `clear_runtime_context()`

This refactor establishes a clean architectural foundation with proper dependency injection, eliminating the global state mutations and tight coupling that existed previously. Both production and validation now use the same bootstrap logic, improving maintainability and reliability.

---

## 2025-09-20 - Align scheduler startup with persistent sync

**Production Startup**: Updated `main.py` to start the `AsyncIOScheduler` paused so it loads the SQLAlchemy job store before `setup_scheduler_jobs`, preventing duplicate job registration and preserving timing.

**Validation Parity**: Adjusted `validation/core/system_controller.py` to mirror the production boot flow (paused start, resume after sync, defensive shutdown) so `system_startup_validation` exercises the same lifecycle.

---

## 2025-09-20 - Complete job serialization fix alignment (Phase 4)

Unified all workflow execution paths to use lightweight, picklable job arguments instead of CoreServices objects.

**Key Changes**:
- **Enhanced job argument construction**: Modified create_job_args() to accept string global_id parameter directly
- **Updated scheduler calls**: All job creation now uses create_job_args(assistant.global_id) for consistency
- **Aligned API services**: Manual execution endpoints now use job_args instead of CoreServices
- **Updated validation framework**: Test execution now uses job_args with proper data root isolation
- **Cleaned imports**: Removed unused imports and simplified function signatures

**Technical Impact**:
- Unified architecture: All execution paths (scheduled, manual API, validation) now use identical job_args structure
- Serialization safety: Eliminates all SQLAlchemy job store serialization issues
- Memory efficiency: No more storing heavy database objects in job arguments
- Test isolation: Validation framework maintains proper data root separation
- Production ready: All execution paths verified working with basic_haiku scenario

**Result**: Job serialization issue fully resolved across all system components.

---

## 2025-09-17 - Logfire Always-On Instrumentation

**Simplified Observability**: Refactored UnifiedLogger to provide always-on Logfire instrumentation with console fallback, eliminating conditional logic and improving developer experience.

**Key Changes**:
- **Always Available**: Rich console instrumentation now works automatically without configuration
- **Smart Cloud Integration**: Set `LOGFIRE_TOKEN` to send data to Logfire dashboard; otherwise console-only mode
- **Simplified Architecture**: Removed 30+ conditional `if self._logfire:` checks throughout codebase
- **Better DX**: Lazy initialization ensures validation framework and environment loading work correctly
- **Dual Experience**: Console shows high-level traces; Logfire dashboard provides detailed drill-down

**User Impact**: Local development now shows rich instrumentation by default, while production environments get the same enhanced observability when tokens are configured.

---

## 2025-09-17 - Refactor UnifiedLogger activity logging

**Centralized activity log**: Replaced `logger.vault_log` with keyword-only `logger.activity()` writing JSON lines to `system/activity.log` via a rotating handler.
- Removed legacy vault markdown logging helpers and migrated all call sites to the new API with explicit metadata.
- Updated architecture docs and contributor guidance; validated with `python validation/run_validation.py run --scenarios basic_haiku`.

---

## 2025-09-15 - Enhanced Status Endpoint Performance

**Status Endpoint Optimizations:**
- **Cached Data Usage**: Status endpoint now uses cached assistant and vault data instead of reloading from filesystem
- **Extended AssistantLoader**: Added vault discovery caching to reduce filesystem operations  
- **Enhanced Scheduler Status**: Status endpoint now extracts rich job data directly from APScheduler including next run times, trigger details, and job configuration
- **Removed Vault Creation**: Cleaned up deprecated vault creation from template functionality
- **Performance Improvement**: Status checks are now near-instant using cached data rather than full system reload

---

## 2025-09-15 - Complete Phase 3: Intelligent Job Synchronization (Phase 3)

**Phase 3 Implementation Complete**

- **AssistantLoader Refactor**: Assistant.trigger now stores actual APScheduler trigger objects instead of ParsedSchedule wrappers
- **Intelligent Job Synchronization**: Jobs are only replaced when schedule or workflow actually changes, preserving timing state for unchanged configurations  
- **Critical Bug Fix**: Fixed trigger comparison using string comparison (`str(trigger1) != str(trigger2)`) since APScheduler triggers do not support direct equality comparison
- **Clean Comparison Logic**: Direct trigger comparison replaces complex string-based comparisons
- **Parameter Clarity**: Renamed `force_reload` → `manual_reload` to clarify that both startup and manual rescans preserve timing
- **Proper Typing**: Assistant.trigger typed as `Optional[BaseTrigger]` instead of generic `Any`
- **API Compatibility**: Updated API services to extract schedule information from trigger objects
- **Persistent Storage Verified**: Confirmed APScheduler SQLAlchemy job store properly persists jobs across container restarts
- **Full System Validation**: All components (CoreServices, validation framework, job scheduling) updated and tested
- **Manual Testing**: Comprehensive scenarios verified including schedule changes, description changes, new assistants, and workflow change detection

**Benefits**: Config changes no longer reset job timing unless schedule actually changed. Clean architecture following coding standards with no unnecessary abstraction.

---

## 2025-09-14 - AssistantConfig to Assistant Class Refactor (Phase 2.5)

**Major Architecture Refactor**: Replaced AssistantConfig with new Assistant class that stores fully parsed objects instead of raw strings.

**Key Improvements**:
- ✅ **Eliminated Duplicate Parsing**: Schedule parsing now happens once during loading (not twice during validation and job creation)
- ✅ **Eliminated Duplicate Workflow Loading**: Workflow modules loaded once during Assistant creation, cached for reuse
- ✅ **Performance Gains**: Faster job creation, API responses, and manual execution due to cached parsed objects
- ✅ **Clean Error Handling**: Removed unnecessary try/catch blocks, errors bubble up naturally following coding standards
- ✅ **Early Error Detection**: Invalid schedules and workflows caught during Assistant loading, not at runtime

**Technical Changes**:
- Created new Assistant dataclass with ParsedSchedule objects and cached workflow functions
- New AssistantLoader class with load_assistants() method (renamed from confusing load_config())
- Updated core/scheduling/jobs.py to use parsed objects directly (no duplicate parsing)
- Updated api/services.py to use cached workflow functions (no duplicate loading)
- Updated core/core_services.py, validation/core/system_controller.py to use new Assistant objects
- Minimized old code exports, kept only essential create_vault_from_template() function

**Architecture Benefits**:
- **Ready for Phase 3**: Job comparison now trivial (Assistant.schedule vs APScheduler trigger objects)
- **Cleaner Codebase**: Clear separation between loading (parsing) and usage (cached objects)
- **Validation Verified**: All scenarios pass (100% success rate), no user-facing changes

**Files Modified**: core/assistant/loader.py, core/scheduling/jobs.py, api/services.py, core/core_services.py, validation/core/system_controller.py, main.py, plus new core/assistant/assistant.py

This refactor enables intelligent job synchronization for the persistent job store (Phase 2.5 → Phase 3).

---

## 2025-09-14 - Refine Model Thinking Parameter

Simplified thinking parameter implementation after troubleshooting cross-provider inconsistencies. **Anthropic**: Fully functional thinking support with 2000 token budget. **OpenAI/Google/Mistral**: Commented out custom configurations due to API complexity - models use their default reasoning behavior. Updated documentation to reflect experimental status and provider-specific guidance. Prioritized system stability over feature completeness.

---

## 2025-09-13 - Model Directive Thinking Support

Added thinking/reasoning parameter support to @model directive for enhanced AI capabilities across providers. Users can now enable model thinking with @model name (thinking) syntax. **Anthropic**: Enables thinking with token budget configuration. **OpenAI**: Activates reasoning effort with detailed summaries. **Google**: Explicitly controls Gemini thinking (disabled by default to normalize behavior). **Mistral/Ollama**: Limited support (Magistral has automatic thinking). Thinking is disabled by default for consistent behavior across all providers.

---

## 2025-09-12 - Implement modular documentation system and interactive setup foundation

Major refactoring to replace template-based vault creation with interactive setup assistant: renamed sequential_generator workflow to 'step' for clarity, restructured /docs with modular system (core/, workflows/, development/, setup/), created documentation access tool for version-matched doc access, removed template system infrastructure, established foundation for marimo-based interactive setup assistant. This enables conversational assistant creation with AI that has access to current documentation instead of copying stale template files.

---

## 2025-09-11 - Fix Assistant Visibility Bug in Dashboard Interfaces

Fixed bug where assistants were not appearing in dashboard and interactive workflow interfaces. Root cause was bare exception handler silently catching Pydantic validation error when AssistantSummary.schedule_cron expected string but received None for manual-only assistants. Applied fail-fast principle by removing bare exception handler and updating model to handle Optional[str] schedule.

---

## 2025-09-11 - Made Schedule Parameter Optional for Manual-Only Assistants

Made schedule parameter optional in assistant configuration - assistants without schedules are manual-only and can be executed via API. Removed force parameter from manual execution since users clearly intend to run assistants when executing manually, regardless of enabled status. Updated documentation to clarify that enabled flag only affects scheduled execution. Cleaned up all UIs (Marimo dashboard, CLI launcher) to remove force-related options.

---

## 2025-09-11 - Interactive Workflow Prompt History Improvements

Completely redesigned prompt history formatting for maximum compactness and utility: changed section header from PROMPT_HISTORY to PROMPT HISTORY, made timestamps bold instead of headers, added complete configuration snapshots including raw directives and instructions text in single-line format, and switched to Obsidian wikilink format [[file]] for file references. History entries now capture the complete assistant state for easy reproduction.

---

## 2025-09-11 - Enhanced Assistant File Reference Documentation

Added comprehensive Complete Pattern Reference section to assistant-file-reference.md with organized time-based, file collection, and glob patterns. Updated directive documentation to include new {day-name} and {month-name} patterns and Obsidian hotlink support.

---

## 2025-09-11 - Obsidian Hotlink Support

Added automatic square bracket stripping for @input-file and @output-file directives, enabling seamless Obsidian drag-and-drop file linking. Users can now use `@input-file [[goals.md]]` format. Updated documentation with required Obsidian settings (Use Wikilinks + Absolute path in vault).

---

## 2025-09-11 - Added {day-name} and {month-name} Pattern Variables

Added new pattern variables `{day-name}` and `{month-name}` to header and output-file directives for dynamic day and month name resolution (e.g., "Monday", "January"). Updated pattern resolution in PatternUtilities and directive documentation.

---

## 2025-09-11 - Performance optimization and scheduling improvements

**Eliminated redundant vault discovery calls during startup** - Fixed duplicate `discover_vaults()` calls in scheduler job setup by using vault information from already-loaded configs instead of re-scanning filesystem. **Optimized workflow directive parsing** - Reduced `parse_directives` calls from 3 to 1 per workflow step by eliminating redundant parsing in `resolve_output_file_path` function and using processed step data directly. **Consolidated scheduling constants** - Moved all scheduling-related constants (`TIMEOUT_MIN`, `TIMEOUT_MAX`, `VALID_WEEK_DAYS`, `DEFAULT_SCHEDULE`) from `core/scheduling/constants.py` to `core/constants.py` for better organization and removed the separate constants file. **Removed problematic "once now" schedule support** - Eliminated confusing "once now" scheduling option that caused unintended executions on container restarts. Updated all validation templates and documentation to use "once at 9am" instead. Added helpful error messages directing users to API endpoints for immediate execution. **Fixed @write-mode new empty file issue** - Removed unnecessary file pre-creation logic that was creating empty numbered files (e.g., newfile_000.md) before actual content files (e.g., newfile_001.md). The @input-file directive already handles missing files gracefully, making pre-creation redundant.

---

## 2025-09-09 - Interactive Workflow Bug Fixes and UI Improvements

**Bug Fixes:**
- **Fixed circular import error** preventing system startup by removing import cycle between main.py and api/endpoints.py
- **Fixed missing dependency** for web_search tool by correcting requirements.txt from `ddgs` to `duckduckgo-search` package
- **Added @output-file directive support** to interactive workflow - AI responses now properly written to specified output files with timestamp headers and directory creation
- **Fixed Marimo interface display issues** with proper variable scoping and state management between reactive cells

**UI Improvements:**
- **Added rescan button** to Marimo interactive workflow interface for refreshing assistant list without cell re-execution
- **Enhanced error handling** and status feedback in web interface
- **Improved response display** with better markdown rendering and content formatting
- **Added debug capabilities** for troubleshooting API response flow

**System Validation:** All core functionality verified stable through validation scenarios after fixes.

---

## 2025-09-09 - Interactive Workflow System Implementation

**Complete Interactive Workflow Feature**: Implemented comprehensive interactive workflow system enabling users to submit prompts to AI assistants for autonomous file operations and real-time content creation.

**Core Features:**
- **Interactive Workflow Engine**: New workflow type that processes user prompts in real-time with AI-driven file operations and autonomous decision-making
- **File Operations Tool**: Enhanced tool with comprehensive vault-bounded file management (read, write, append, move, list, mkdir) with security boundaries
- **Prompt History Tracking**: Automatic logging of all interactions in assistant markdown files with clickable file links and timestamps

**API Integration:**
- **REST Endpoint**: Added `POST /api/interactive/prompt` for real-time prompt submission to interactive assistants  
- **Service Layer**: Clean service implementation using CoreServices pattern for workflow execution
- **Response Format**: Simple LLM response string for clean API integration

**System Integration:**
- **Scheduler Filtering**: Interactive assistants automatically discovered but excluded from scheduled execution (API-only workflow type)
- **Parser Architecture**: Refactored to support workflow-specific section interpretation enabling flexible directive usage
- **Import Cleanup**: Fixed all inline import violations throughout codebase per CLAUDE.md guidelines

**User Interface:**
- **Marimo Interface**: Simple web interface at `marimo/notebooks/interactive_workflow.py` with container-ready design
- **Clear UX**: Explicit messaging that this is NOT conversational AI - single prompt/response with history saved in assistant files
- **API Integration**: Direct integration with interactive workflow endpoint for real-time testing

**System Validation**: All core functionality remains stable with no breaking changes to existing workflows or scheduled assistants.

**User Impact**: Users can now create interactive workflow assistants that autonomously manage files and respond to real-time prompts through both API and web interface, with complete interaction history automatically tracked.

---

## 2025-09-08 - Simplify CoreServices instantiation to use global_id as primary interface

**Simplified CoreServices Constructor**:
- Replaced complex 5-parameter constructor with simple `CoreServices(global_id)` interface
- Added optional `_data_root` parameter with `CONTAINER_DATA_ROOT` default
- Automatically resolves all parameters (vault_name, assistant_file_path, week_start_day) from global_id
- Implements config_manager lookup with manual file parsing fallback

**Updated All Usage Patterns**:
- **API Services**: Uses simple `CoreServices(global_id)` with defaults
- **Scheduler**: Uses `CoreServices(global_id, _data_root=config_manager._data_root)` to preserve override chain
- **Validation Framework**: Uses `CoreServices(global_id, _data_root=test_path)` for test isolation

**ConfigManager Privacy**:
- Renamed `data_root` to `_data_root` to signal private usage
- Maintains override capability for validation framework test isolation

**Benefits**:
- **Ultra-simple interface**: Most usage becomes just `CoreServices(global_id)`
- **Self-contained**: No mandatory dependencies on config_manager
- **Preserved functionality**: All test isolation and override mechanisms maintained
- **Backward compatible behavior**: Same workflow execution, simplified interface

**Validation**: All scenarios pass, including test isolation verification

---

## 2025-09-07 - CoreServices Workflow Context Refactor (Phase 1-4 Complete)

**Implemented unified CoreServices interface for workflow development**

- **CREATED**: `core/core_services.py` - Unified interface providing path management, assistant parsing, directive processing, and LLM interaction through dependency injection
- **MODIFIED**: `core/scheduling/jobs.py` - Updated to create CoreServices with vault_name and _data_root for proper path injection  
- **MODIFIED**: `workflows/sequential_generator/workflow.py` - Refactored to use CoreServices API, reduced imports from 5+ modules to 2 (CoreServices + UnifiedLogger)
- **MODIFIED**: `validation/core/workflow_execution_service.py` - Updated to use CoreServices with test-isolated paths for clean dependency injection
- **REORGANIZED**: Moved `assistant_loader.py` and `assistant_parser.py` to `core/assistant/` submodule for better organization
- **REMOVED**: Complex monkey patching from validation framework, replaced with clean dependency injection
- **FIXED**: File output path isolation - validation tests now create files in test directories instead of global `/app/data/`

**Path Construction Logic**: CoreServices takes `vault_name` and `_data_root` separately, constructs `vault_path = os.path.join(_data_root, vault_name)` internally for proper dependency injection and test isolation.

**Developer Experience**: Workflows now import only 2 modules (CoreServices + UnifiedLogger) instead of 5+ core services, with flexible **kwargs signature for future extensibility.

**BREAKING CHANGE**: Workflow signature changed from `run_workflow(vault_path, file_path, week_start_day, global_id)` to `run_workflow(services: CoreServices, **kwargs)`

---

## 2025-09-06 - Complete Parser Architecture Refactoring and File Operations Tool (Phase 1-2)

**Phase 1: Parser Architecture Refactoring ✅ COMPLETED**

- **MODIFIED:** `core/assistant_parser.py` - Removed INSTRUCTIONS from reserved_sections
- **REMOVED:** `get_system_instructions()` function (workflows now handle INSTRUCTIONS themselves)  
- **UPDATED:** `workflows/sequential_generator/workflow.py` - Extract INSTRUCTIONS from workflow_sections directly
- **ENHANCED:** Function naming to remove underscore prefix (load_and_validate_config)
- **VALIDATED:** basic_haiku and daily_task_assistant scenarios pass with emoji evidence confirming INSTRUCTIONS are being used

**Phase 2: File Operations Tool Implementation ✅ COMPLETED**

- **ENHANCED:** Complete file_operations tool with 6 operations:
  - `read` - Read file content (safe)
  - `write` - Create new files only (fails if exists) 
  - `append` - Add content to existing files only (fails if missing)
  - `move` - Move/rename files (fails if destination exists)
  - `list` - Find files with glob patterns (recursive vault exploration)
  - `mkdir` - Create directories (safe with exist_ok=True)
- **ADDED:** Comprehensive security boundaries:
  - Vault boundary enforcement preventing path escape
  - Path sanitization blocking `../` traversal and absolute paths
  - Markdown-only file enforcement (rejects non-.md extensions)
  - Safe-only operations preventing data loss with helpful error messages
- **MODIFIED:** Enhanced tool architecture with vault context injection:
  - Updated `core/tools/base.py` to accept optional vault_path parameter
  - Modified `core/directives/tools.py` to pass vault_path to all tools
  - Updated all existing tools for compatibility
- **VALIDATED:** Comprehensive testing with file_operations_test scenario (12 successful tool calls)

**Result:** Foundation complete for Interactive Workflow - AI agents have secure file management within vault boundaries! 🚀

---

## 2025-09-05 - Fix section name parsing regex

Fixed workflow stopping issue where only the first step would execute when section names contained hyphens or other special characters.

**Root Cause:** The regex pattern for parsing markdown sections was overly restrictive, using `[A-Za-z0-9_ ]` character class that excluded hyphens. Section names like "Analysis-questions" would fail to match, causing the parser to only find sections up to the first unmatched name.

**Solution:** Simplified regex from character validation approach to structural parsing approach using `.+?` to capture any characters after `## ` delimiter until newline.

**Impact:** 
- Workflows now process all steps instead of stopping after first step with special characters in name
- More robust section parsing that handles any valid markdown header format
- Eliminates future parsing failures from restrictive character validation

---

## 2025-09-03 - Fix step header parsing and enhance @run-on directive

Fixed step header parsing to allow spaces and added new @run-on directive options for better workflow control.

**Step Header Parsing Fix:**
- Updated regex in `core/assistant_parser.py` to allow spaces in step headers
- Now supports headers like `## STEP 1`, `## DAILY TASKS`, `## MORNING ROUTINE`
- Maintains backward compatibility with existing underscore format (`## STEP_1`)

**@run-on Directive Enhancements:**
- Added `daily` option for explicit daily execution (same as default behavior but self-documenting)
- Added `never` option to disable step execution without deletion
- Smart precedence: `never` > `daily` > specific days
- Updated directive validation in `core/directives/run_on.py`
- Updated workflow logic in `workflows/sequential_generator/workflow.py`

**User Impact:**
- More readable step headers with natural spacing
- Better workflow documentation with explicit `@run-on daily`
- Easy step disabling with `@run-on never` for maintenance/testing
- All existing functionality preserved

**Examples:**
```markdown
## DAILY TASKS
@run-on daily

## ARCHIVED STEP
@run-on never

## WEEKLY REVIEW
@run-on friday
```

---

## 2025-09-03 - Add API timeout configuration

Implemented unified timeout system for all external API calls to improve system reliability and prevent potential hanging processes.

**Changes:**
- Added `DEFAULT_API_TIMEOUT` constant (120 seconds default)
- Updated all AI models (Gemini, Anthropic, OpenAI, Mistral, Ollama) with `ModelSettings(timeout=120)`
- Added timeout configuration to web search tools (DuckDuckGo with custom timeout)
- Added timeout configuration to Tavily crawl and extract tools (respects 120s API limit)
- Updated `.env.example` with `DEFAULT_API_TIMEOUT` documentation

**User Impact:**
- External API calls now timeout after 2 minutes instead of potentially hanging indefinitely
- System fails gracefully on network issues rather than getting stuck
- Configurable via `DEFAULT_API_TIMEOUT` environment variable
- All external services (AI models, web search, crawl tools) use unified timeout

**Validation:**
- ✅ All tool scenarios pass (web_search_assistant, tavily_crawl_assistant, tavily_extract_assistant)
- ✅ Basic validation scenarios continue working
- ✅ Timeout configuration loads correctly across all components

**Note:** This addresses one potential cause of system hangs but may not resolve all performance issues.

---

## 2025-09-01 - Add Ollama support for local AI inference

Implemented complete Ollama integration allowing users to run local AI models. Added ollama provider to mappings.yaml with customizable base_url configuration. Users can now use @model ollama in assistant files to connect to local Ollama server. Includes proper error handling, API key validation bypass, and seamless integration with existing model directive system. Also refactored default model handling to create_agent() for better separation of concerns.

---

## 2025-09-01 - Add @header directive for custom step headers

Implemented new @header directive that allows controlling the header written above each step content. Supports both literal text and pattern variables like {today}, {this-week}, etc. Users can now customize step headers instead of relying on default format.

---

## 2025-08-31 - Modern Docker setup with UV and file permissions

Created new efficient Docker setup with:
- **Multi-stage Dockerfile** using UV for faster dependency management
- **File permission solution** with configurable UID/GID build args  
- **Root-level pyproject.toml** replacing requirements.txt
- **Configurable API port** via environment variables
- **Non-root container user** for better security
- **docker-compose.modern.yml.example** for testing new setup

The new setup addresses three key issues:
1. More efficient container images with better layer caching
2. File permission problems for local users (files created by container now editable by host user)
3. Modern dependency management with UV and pyproject.toml

Users can test the new setup alongside the existing one before migrating.

---

## 2025-08-31 - Complete Pydantic AI Directive Refactoring (Phases 1-4)

Refactored model and tools directives to follow Pydantic AI patterns for improved architecture and performance. **Architecture:** Transformed `create_agent()` to pure composition, model directive returns Pydantic AI model instances, tools directive returns tool functions and enhanced instructions. **Validation:** All scenarios pass including new multi-tool workflow test. **Performance:** Cleaner separation of concerns, foundation for future model parameter configuration. **Compatibility:** Full backward compatibility maintained for `@model` and `@tools` syntax.

---

## 2025-08-31 - Fixed Documentation and Implementation Gaps

Resolved inconsistencies between documented directive behavior and actual implementation to ensure the system works exactly as documented.

**Directive Behavior Fixes:**
- Made `@output-file` truly required by removing default `journal/{this-week}` behavior from workflow
- Made `@run-on` truly optional by providing default behavior (runs every day) when not specified
- Steps now throw clear errors when required directives are missing

**Documentation Updates:**
- Updated assistant file reference to correctly classify directives as required vs optional
- Added comprehensive `@tools` directive documentation including all supported formats
- Updated README.md to reflect actual system behavior without misleading defaults

**Registry Cleanup:**
- Fixed directive registry to remove calls to non-existent documentation methods
- Streamlined registry interface to match actual base class implementation

**Key Changes:**
- `@output-file` now mandatory - steps without it will error with clear message
- `@run-on` now optional - steps without it run every day by default
- `@tools` supports boolean values (`true`, `false`) and keywords (`all`, `none`)
- Documentation accurately reflects implementation behavior

---

## 2025-08-31 - Consolidated Model and Tool Configuration

Unified system configuration by moving model mappings into the shared mappings.yaml file alongside tool configurations. This eliminates code duplication and provides a single source of truth for both models and tools configuration.

**Model Configuration Changes:**
- Moved all model mappings from hardcoded dictionaries in `core/llm/models.py` to `core/mappings.yaml`
- Restructured YAML to separate providers (with API keys) from models to eliminate repetition
- Each provider defines its API key once, models reference the provider

**Implementation Updates:**
- Updated `core/llm/models.py` to read from YAML instead of hardcoded mappings
- Maintained full backward compatibility with existing functions and interfaces
- All existing model resolution and validation continues to work unchanged

**Benefits:**
- Single configuration file for both tools and models
- Reduced maintenance overhead when adding new models or providers
- Consistent configuration architecture across the system
- Cleaner separation of concerns between configuration and logic

---

## 2025-08-30 - Tavily Extract and Crawl Tools Implementation

Added two new Tavily tools: **TavilyExtract** for URL content extraction with support for single URLs and URL lists, extraction depth (basic/advanced), and markdown output. **TavilyCrawl** for intelligent website crawling with API parameters (max_depth, max_breadth, limit, extract_depth) and comprehensive site exploration. Fixed validation framework by removing artificial timeouts to match production behavior.

---

## 2025-08-28 - Refactor validation framework from V2 to unified validation

**Major validation framework consolidation and refactoring**

- **Removed old validation framework**: Deleted legacy V1 validation system
- **Renamed validation_v2 to validation**: Unified under single validation directory
- **Refactored scenario discovery**: Changed from directory-based to BaseScenario subclass introspection for simpler organization
- **Updated all import paths**: Fixed references throughout codebase from validation_v2 to validation
- **Cleaned CLI interface**: Updated ValidationRunner class name and all help text
- **Enhanced scenario structure**: Scenarios now live as direct .py files in scenarios/ directory
- **Comprehensive testing**: Verified all 4 scenarios (basic_haiku, daily_task_assistant, web_search_assistant, code_execution_assistant) work correctly
- **Template organization**: Structured validation templates with assistants/ and files/ subfolders

The validation framework is now clean, unified, and easier to work with. No more V1/V2 confusion!

---

## 2025-08-27 - V2 Validation Framework Monkey Patch Solution

**Complete path and date isolation for scheduled job execution**

**Path Isolation:**
- Apply CONTAINER_DATA_ROOT patch before module imports in SystemController
- Defer core imports until after patch application  
- Redirect scheduled jobs to test directories instead of production

**Date Isolation:**
- Add set_test_date method with custom MockDateTime class
- Patch workflows.sequential_generator.workflow.datetime for scheduled jobs
- Enable predictable file naming in validation scenarios

**System Integration:**
- Update SystemController with real vault discovery and scheduler setup
- Add scheduler job creation, execution tracking, and manual triggering
- Implement complete startup → job creation → execution → validation flow

**API Improvements:**
- Combine trigger_job_manually + wait_for_scheduled_run into single trigger_job method
- Cleaner validation scenarios with atomic job execution
- Enhanced timeline logging for better debugging

**Documentation:**
- Update WorkflowContext spec with real-world validation insights
- Add monkey patch refactor map for future WorkflowContext implementation
- Document time control patterns in validation framework README

**Results:** basic_haiku scenario passes with complete system integration, files created in test directories with correct test dates

---

## 2025-08-27 - Validation Framework V2 - Real Workflow Integration

**Transformed V2 from file management testing to real product functionality validation.** **Core Achievement:** BaseScenario.run_assistant() now executes actual workflows with real AI models, complete environment isolation, and comprehensive evidence collection. **Infrastructure Complete:** Real workflow execution via WorkflowExecutionService, datetime control for @run-on directive testing, vault logging isolation (with module caching bug workaround), file state isolation for {pending} patterns, TestModel integration using existing core @model mapping, automatic .env loading for dev container/docker/CI contexts. **Validation:** Successfully tested with Gemini Flash generating real haiku content in 4.66 seconds with complete isolation. **Architecture:** Single CONTAINER_DATA_ROOT patch redirects all file operations to test directories, preserves excellent evidence collection, maintains BaseScenario boundary enforcement. **Developer Impact:** V2 scenarios now test actual product functionality (workflows, AI, scheduling, directive processing) instead of just file operations. Framework ready for core scenario development.

---

## 2025-08-26 - Complete Validation Framework V2 Implementation

**Implemented user-focused validation framework with BaseScenario boundary enforcement, real assistant files, flexible vault management, and comprehensive evidence collection. All 7 phases complete including infrastructure, documentation, and integration.**

---

## 2025-08-24 - Complete Tool Use Framework Documentation (Phase 7)

Comprehensive documentation updates for the tool integration framework. **Updates:** Added `@tools` directive documentation to assistant file reference, updated README.md with high-level tool integration overview, enhanced architecture.md with complete tool framework section including architecture components, data flows, usage patterns, and extension guides. **Developer Guide:** Added detailed instructions for creating new tools including BaseTool implementation, dependency management via requirements.txt, tool registration in mappings.yaml, and design principles. **User Impact:** Complete documentation enabling users and developers to understand and extend the AI tool capabilities.

---

## 2025-08-24 - Complete Tool Use Framework Implementation (Phase 5)

Implemented complete tool integration framework enabling AI agents to use external tools through `@tools` directive. **Key Features:** Granular per-step tool selection (`@tools web_search`, `@tools code_execution`), dynamic tool loading with introspection, automatic system prompt enhancement, clean architecture with BaseTool classes. **Integration:** Tools directive returns tool classes, `create_agent()` handles processing and instruction enhancement, workflows remain simple. **Validation:** Tested with TestModel (automatic tool calling) and real Gemini model (intelligent contextual usage). Users can now add `@tools web_search` to workflow steps for intelligent web search capabilities.

---

## 2025-08-23 - Centralized Directive Value Parsing (Phase 3)

Implemented centralized value parsing utilities in `core/directives/parser.py` to eliminate parsing inconsistencies across directive processors. The `DirectiveValueParser` class provides standardized methods for list parsing, boolean parsing, and validation. Updated existing directives (`@run-on`, `@write-mode`, `@model`) to use centralized parsing. **Breaking change:** `@run-on` directive now supports both comma and space separation (e.g., `@run-on monday tuesday` or `@run-on monday, tuesday`).

---

## 2025-08-21 - Sequential Generator Workflow Refactoring (Phase 1)

**Breaking down monolithic workflow function for maintainability and tool integration readiness**

- **REFACTOR:** Extracted `_load_and_validate_config()` method from monolithic `run_workflow()` function
- **REFACTOR:** Extracted `_initialize_workflow_context()` method for workflow execution context setup  
- **REFACTOR:** Extracted `_process_workflow_step()` method for individual step processing logic
- **REFACTOR:** Extracted `_create_step_agent()` method for AI agent creation (positioned for Phase 4 tool integration)
- **REFACTOR:** Extracted `_write_step_output()` method for file writing operations
- **CLEANUP:** Consolidated duplicated output file path resolution logic into `_resolve_output_file_path()`
- **CLEANUP:** Extracted complex input file formatting into `_build_final_prompt()` helper function
- **CLEANUP:** Extracted run-on validation logic into `_should_step_run_today()` helper function
- **FIX:** Resolved all lint warnings (unused imports, variable assignments, import order)
- **TEST:** Added comprehensive bash tests validating all extracted functions and end-to-end workflow execution

**Result:** Transformed 330+ line monolithic function into clean orchestration with 8 focused helper functions. Zero behavioral regressions, all tests pass, lint-clean code ready for tool integration.

---

## 2025-08-20 - Improved numbered file generation for write-mode new

Fixed **@write-mode new** to generate zero-padded 3-digit numbered files (planning_001.md, planning_002.md) instead of simple incrementing numbers. This ensures proper alphabetical sorting in file browsers when file counts exceed 9.

---

## 2025-08-20 - Comprehensive assistant file reference documentation

Created complete **assistant-file-reference.md** with structured documentation covering: YAML frontmatter configuration, workflow step sections, all 5 available directives (@run-on, @output-file, @input-file, @model, @write-mode), time and file patterns, schedule syntax, security restrictions, and best practices. This provides a reusable reference for the setup-assistant and improves user onboarding.

---

## 2025-08-19 - Add @write-mode directive for file creation control (Phase 1-3)

**New @write-mode directive** allows users to control how content is written to output files:

- **@write-mode append** (default): Appends content to existing files, building cumulative documents over time
- **@write-mode new**: Creates numbered files for each run (e.g., journal/2025-08-19_0.md, journal/2025-08-19_1.md), preserving individual outputs

**Use Cases:**
- Daily journal entries as separate files vs. cumulative daily file
- Meeting notes with versioning for each agenda iteration  
- Analysis reports that should be kept separate vs. building summary documents

**Implementation:**
- Core directive processor validates and normalizes values
- Workflow applies numbering logic with gap-filling (lowest available number)
- Maintains proper separation of concerns (core handles validation, workflow handles business logic)
- Updated documentation in README.md, WELCOME.md, and architecture.md

**Example:**
```markdown
## STEP1
@output-file daily/{today}
@write-mode new
Generate today's tasks.
```

Results in numbered files: daily/2025-08-19_0.md, daily/2025-08-19_1.md, etc.

---

## 2025-08-19 - YAML Frontmatter Migration and Section Name Improvements

**Migrated assistant configuration from sections to YAML frontmatter with enhanced Obsidian integration**

- **Replace section-based config** with YAML frontmatter format for cleaner, standard configuration
- **Add comprehensive frontmatter parsing** with robust error handling and YAML syntax validation
- **Enable Obsidian integration** with native properties panel support and Dataview compatibility
- **Support custom properties** in frontmatter for user classification (category, priority, tags, author, etc.)
- **Shorten section names** from `## ASSISTANT_SYSTEM_INSTRUCTIONS` to `## INSTRUCTIONS` for better usability
- **Update all templates** to use new frontmatter format with clean visual structure
- **Enhance error messages** to reference YAML frontmatter syntax instead of deprecated sections
- **Maintain full compatibility** for workflow section processing and system instructions extraction
- **Remove deprecated functions** (`get_config_section`, `parse_config_section`) for cleaner architecture
- **Update documentation** (README, templates, examples) to reflect modern frontmatter format

New assistant file format features YAML frontmatter for configuration, shortened section names, and seamless Obsidian properties integration for enhanced organization and querying capabilities.

---

## 2025-08-16 - Pydantic Configuration Validation Refactor (Completed all 3 phases)

**Enhanced assistant configuration validation with Pydantic schema**

- **Replaced manual validation** with robust Pydantic schema in `core/assistant_parser.py`
- **Improved error messages** with field-specific validation details and helpful suggestions
- **Added automatic defaults** for `week_start_day` (monday) and `description` (empty)  
- **Integrated schedule validation** using existing schedule parser for comprehensive syntax checking
- **Removed timeout parameter** completely from code, templates, and documentation (unused feature)
- **Enhanced validation strictness** with `extra="forbid"` to reject unknown configuration fields
- **Preserved API compatibility** while improving validation quality and maintainability
- **Reduced code complexity** from ~50 lines of manual validation to ~15 lines of declarative schema

All validation errors now provide clear, actionable feedback during assistant loading rather than cryptic runtime failures.

---

## 2025-08-14 - Graceful configuration error handling

System now continues operating when assistant files have configuration errors. Malformed assistant files no longer crash the entire system - instead, errors are collected and displayed in the `/api/status` endpoint for easy visibility. Valid assistants continue to work normally while users can identify and fix problematic configurations.

---

## 2025-08-11 - Fix Docker file permission issues

**Added UID/GID environment variables** to docker-compose.yml to fix file permission issues. Files created by the container are now owned by the specified user instead of root, making them editable on the host system. Added documentation to README and .env.example.

---

## 2025-08-11 - Fix double .md extension in output files

**Fixed duplicate .md extensions** when users specify @output-file with .md extension. The OutputFileDirective now normalizes extensions by stripping any existing extension and ensuring exactly one .md extension. Also enforces markdown-only constraint by converting other extensions (e.g., .txt, .csv) to .md.

---

## 2025-08-10 - Fix Critical Post-Refactoring Issues

Fixed three critical issues discovered during user testing after core module restructuring:

**API Import Issues** 
- Fixed broken imports in api/services.py after core module refactoring
- Updated imports from core.assistant_config to core.assistant_loader
- Restored vault creation and assistant execution API functionality
- All API endpoints now working correctly

**CLI Launcher jq Dependency**
- Removed hard dependency on jq for CLI launcher functionality  
- Added graceful degradation with fallback JSON parsing functions
- CLI now works fully without jq, with clear installation guidance
- Added OS-specific jq installation instructions (apt, yum, brew, pacman)
- All commands (status, create, run, rescan) functional without jq

**Marimo Proxy Configuration**
- Fixed broken reverse proxy setup after marimo decoupling
- Moved docker-compose.override.yml.example to /marimo/ directory
- Created dedicated .env.example for marimo with proxy configuration
- Enhanced launcher to copy .env.example and update TZ automatically  
- Removed MARIMO_DOMAIN from main project .env.example (belongs in marimo)
- Updated marimo README with complete reverse proxy setup instructions

All fixes maintain backward compatibility while improving user experience and system maintainability.

---

## 2025-08-10 - Schedule Parsing Refactor Complete (Phases 1-4)

**Replaced AI-dependent natural language scheduling with local structured syntax**

**Breaking Change**: Schedule syntax changed from natural language (e.g. `schedule: weekdays at 8am`) to structured format (e.g. `schedule: every 1d at 8am`).

### Major Changes:

**New Scheduling Module (`core/scheduling/`)**:
- ✅ **Local parsing** - Zero external dependencies, no LLM API calls during startup
- ✅ **Structured syntax** - `every 1d at 8am`, `every 2h`, `once at 10:00`, etc.
- ✅ **Multiple trigger types** - IntervalTrigger, DateTrigger (no more cron-only)
- ✅ **Performance improvement** - Dramatically faster startup/rescan operations

**Architecture Improvements**:
- ✅ **Module consolidation** - All scheduling logic in dedicated `core/scheduling/` module
- ✅ **Clean separation** - Parsing, trigger creation, and job management properly separated
- ✅ **API simplification** - Removed unnecessary wrapper functions for explicit two-step API

**Updated Templates & Documentation**:
- ✅ **Template files** - All vault templates now use new `every 1d at 8am` syntax
- ✅ **Documentation** - README.md, WELCOME.md, and architecture.md fully updated
- ✅ **Clean examples** - No comments in assistant files, clear demonstration through examples

### Migration Required:

Users must manually update existing assistant configurations:
- `schedule: weekdays at 8am` → `schedule: every 1d at 8am`  
- `schedule: daily at 9am` → `schedule: every 1d at 9am`
- `schedule: monday at 6pm` → `schedule: every 1d at 6pm` (use @run-on directive for day filtering)

### Performance Impact:

**Before**: N assistants = N LLM API calls during startup  
**After**: Zero API calls, local parsing only

System startup with 50+ assistants improved from ~30+ seconds to <2 seconds.

---

## 2025-08-09 - Optimize manual assistant execution with targeted config loading

**Performance Enhancement**: Enhanced `load_config()` method to support loading single assistant configurations via `target_global_id` parameter. Manual execution API now loads only the target assistant instead of reloading all system configurations, eliminating unnecessary AI schedule parsing calls and significantly improving execution speed for large systems.

---

## 2025-08-09 - Decouple Marimo Dashboard

Marimo dashboard is now completely separate and optional from the core Project Assistant application. The dashboard connects to the Project Assistant API via host.docker.internal:8000 and can be installed using `./launcher marimo install`. This positions Marimo as "a great way to visualize your Project Assistant data" rather than part of the core stack, providing flexibility while keeping the main application lightweight and focused.

---

## 2025-08-09 - Add Mistral AI Provider Support

Added support for Mistral AI models with three pre-configured aliases: **mistral-large**, **mistral-small**, and **mistral-medium**. Users can now use Mistral models by setting `MISTRAL_API_KEY` environment variable and using `@model mistral-large` in workflow steps or setting `DEFAULT_MODEL=mistral-large` in .env configuration.

---

## 2025-08-08 - Model Selection Directive

**Added per-step model selection with @model directive**

- User-friendly model names (sonnet, gpt-4o, gemini, etc.) map to provider-specific models
- Step-level model selection: `@model sonnet` chooses Claude 3.5 Sonnet for that step
- Hierarchical fallback: @model directive → DEFAULT_MODEL → clear error message
- Support for multiple AI providers: Anthropic, OpenAI, Google, TestModel
- Comprehensive API key validation with helpful error messages
- TestModel integration for fast validation scenarios without API costs
- Simplified validation framework - eliminated complex LLM mocking
- Clean module organization: core/llm/models.py and core/llm/agents.py
- Runtime model switching capability for multi-provider workflows
- Maintains full backward compatibility with existing assistant configurations

---

## 2025-08-06 - Directive-Owned Pattern Resolution Refactor

**Major Architecture Improvement**: Refactored pattern resolution system to use directive-owned pattern processing instead of centralized resolution.

**Key Changes:**
- **New `core/directives/` module** - Organized all directive functionality into cohesive submodule
- **Directive-owned patterns** - Each directive handles its own pattern resolution based on semantic needs
- **Eliminated legacy code** - Removed 365+ lines from `core/pattern_resolution.py` and `core/builtin_directives.py`
- **Enhanced `{pending}` support** - Full implementation of incremental file processing with SQLite state management
- **Improved file sorting** - Uses creation time for chronological ordering, works with any filename
- **Better architecture** - Clear separation of concerns, improved maintainability and extensibility

**User Benefits:**
- **`{pending}` patterns now available** - `@input-file notes/{pending:5}` for incremental processing
- **Works with any file names** - No longer requires date-formatted filenames
- **More reliable processing** - Chronological order based on file creation time
- **Independent state tracking** - Each assistant maintains separate processing history

**Technical Improvements:**
- **Modular design** - Easy to add new directive types and patterns
- **Shared utilities** - Common pattern logic in `PatternUtilities` class  
- **State management** - `AssistantFileStateManager` for persistent file processing history
- **Backward compatibility** - All existing patterns continue to work identically

---

## 2025-08-05 - Manual Assistant Execution API (Phases 1-5: API Models, REST Endpoint, Single-Step Enhancement, Status Enhancement, CLI/Dashboard Integration)

Implemented comprehensive manual assistant execution system with REST API, CLI commands, and admin dashboard integration.

## Core Features
- **REST API Endpoint**: POST /api/assistants/execute for manual workflow execution
- **Single-Step Execution**: Optional step_name parameter to execute individual workflow steps
- **Force Execution**: Ability to execute disabled assistants with force parameter
- **Enhanced Status Endpoint**: GET /api/status now returns detailed assistant lists with global IDs

## User Interfaces
- **CLI Launcher**: Added ./launcher run command with --force and --step options
- **Enhanced Status**: ./launcher status shows available assistants for manual execution
- **Admin Dashboard**: Added execute_assistant() function to marimo notebook

## Key Capabilities
- Execute full workflows or individual steps on-demand
- Bypass @run-on day restrictions for manual execution
- Comprehensive error handling and execution timing
- Assistant discovery through enhanced status endpoints
- Support for all existing directives (@output-file, @input-file, etc.)

## Technical Implementation
- Clean API model design with ExecuteAssistantRequest/Response
- Service layer follows established patterns with proper error transformation
- Workflow function enhanced to support single-step filtering
- CLI implementation uses basic shell tools (no jq dependency)
- All changes are backward compatible

This provides users with surgical control over workflow execution while maintaining the existing scheduled execution functionality.

---

## 2025-08-05 - Complete Simplified Logging Architecture Cleanup

**Cleaned up old logging patterns throughout codebase**

- **Removed manual logger calls**: Eliminated all `logger.info()`, `logger.error()`, `logger.debug()` calls from try/catch blocks throughout core modules
- **Fixed inline logger instantiation**: Removed logger instantiation inside functions, ensuring only module-level loggers exist
- **Removed logger parameters**: Eliminated logger parameters from function signatures - no more passing loggers around as arguments
- **Added missing module loggers**: Added proper module-level logger setup to `core/directive_parser.py` and `core/parameter_registry.py`
- **Updated function signatures**: Removed `logger` parameters from `load_file_with_metadata()` and `load_multiple_files_with_metadata()` functions
- **Added key function decorators**: Applied `@logger.trace()` decorators to critical functions in directive parsing and parameter registry
- **Verified implementation consistency**: All core modules now follow simplified logging pattern: module-level logger + decorators only

**Technical Impact**: System now uses consistent simplified logging architecture with automatic instrumentation providing observability without manual logging clutter. All modules follow the pattern established in the simplified logging specification.

---

## 2025-08-03 - Fix Docker setup and add flexible marimo deployment options

Fixed Docker container issues preventing API and marimo access. Separated FastAPI and marimo into distinct services using official marimo container. Added flexible deployment options supporting both localhost development and reverse proxy setups.

**Docker Architecture Changes:**
- Restored FastAPI startup command to main Dockerfile (without --reload for production)
- Split services: assistant (FastAPI) and marimo (official container)
- Removed complex multi-process command that was causing startup failures
- Fixed marimo service to use official ghcr.io/marimo-team/marimo:latest image

**Marimo Integration:**
- Use official marimo container with proper command syntax
- Support both localhost (http://localhost:8080) and reverse proxy deployments
- Added --proxy flag support for reverse proxy setups (Caddy, nginx, etc.)
- Created docker-compose.override.yml.example for reverse proxy configuration

**Deployment Flexibility:**
- Default: localhost access on port 8080 (works out of the box)
- Reverse proxy: copy override example, set MARIMO_DOMAIN in .env
- Automatic Docker Compose override behavior for seamless switching
- Clear documentation for both use cases

**Configuration:**
- Added MARIMO_DOMAIN environment variable to .env.example
- Proper Docker networking between services
- Security: localhost-only binding for FastAPI (launcher CLI access)
- Network-only access for marimo when using reverse proxy

---

## 2025-08-03 - Rename workflow from weekly_daily_journal to sequential_generator

**Major Workflow Rename**: Renamed `weekly_daily_journal` workflow to `sequential_generator` to better reflect its flexible, general-purpose nature.

**Changes Made**:
- **Module Rename**: `workflows/weekly_daily_journal/` → `workflows/sequential_generator/`
- **Template Updates**: Updated both assistant templates and WELCOME.md to use new workflow name
- **Code References**: Updated all imports, validation scenarios, API services, and core defaults
- **Documentation**: Updated README.md and architecture.md with improved descriptions
- **Validation**: Confirmed all functionality works under new name

**Why This Change**: The original name "weekly_daily_journal" was constraining how users might think to use this flexible workflow. The new name "sequential_generator" better captures its essence: a configurable series of steps that generate markdown content based on AI prompts and context from existing files. Each step can run on specific days and write to different output files, making it suitable for planning workflows, content generation, documentation, and other scheduled markdown creation tasks.

---

## 2025-08-03 - Add marimo admin interface

Implemented web-based admin interface using marimo framework. Added marimo to requirements.txt, updated docker-compose.yml to run both FastAPI and marimo processes in same container. Created simple admin.py interface with buttons for system status, vault rescan, and vault creation using existing API endpoints. Admin interface accessible on port 8001 for proxy access.

---

## 2025-08-01 - Implement Allowed Mocks Registry System

Added framework-approved mocking utilities registry for validation scenarios

**What Changed:**
- Created `validation/core/allowed_mocks.py` with registry of approved mocks
- Added `VaultLoggingMock` for test directory isolation 
- Added `DateTimeMock` for time-dependent feature testing
- Updated `BaseScenario` to provide `self.mocks` registry access
- Fixed Path vs string issue in vault logging mock
- Updated validation README to document registry approach

**Benefits:**
- **Discoverable**: `self.mocks.get_mock()` shows available exceptions
- **Controlled**: Only registry mocks allowed, prevents unit testing drift
- **Simple**: Clean implementation following CLAUDE.md guidelines
- **Extensible**: Easy to add new approved mocks

**Usage:**
```python
# Use approved mocks through registry
with self.mocks.get_mock("datetime").create_context(test_date):
    await run_workflow(...)
```

Scenarios must only use registry mocks - any other mocking indicates drift toward unit testing.

---

## 2025-08-01 - Complete Phase 7: Selective Manual Instrumentation (Phase 7)

**Phase 7 Implementation Completed**: Successfully implemented comprehensive logging architecture with both technical observability and user activity logging.

## Key Achievements

### Instrumentation & Observability
- **Strategic @logger.trace Decorators**: Added manual instrumentation to critical functions across core modules
  - Workflow execution (`run_workflow`, `run_step`)
  - Configuration management (`assistant_config_loading`, `parse_config_section`, `vault_discovery`) 
  - Scheduler operations (`setup_scheduler_jobs`)
  - Directive processing (`process_step_content`)
  - LLM interfaces (`create_agent`, `generate_response`)

### User Activity Logging
- **Comprehensive Vault Logging**: Implemented `logger.vault_log()` calls for user-visible activities
  - Workflow completion/failure messages with context (global_id, steps, files)
  - Configuration errors with actionable fix suggestions
  - Schedule updates when assistant configurations change
  - File creation failures during workflow execution

### Production Safety & Validation
- **Vault Context Detection**: Comprehensive review confirmed robust production safety
  - Explicit `global_id` parameters used throughout production code
  - Multiple fallback detection strategies (vault paths, file paths, parameter combinations)
  - AssistantConfig provides consistent vault/assistant format via `global_id` property
  - Graceful silent fallback when context cannot be determined

### Issue Resolution
- **Validation Scenario Fix**: Resolved vault/global_id mismatch in test scenarios
  - Issue was isolated to validation implementation only - no production impact
  - Fixed test vault naming consistency (`RunOnTestVault/run_on_test`)
  - Validated unified vault logging with all files in correct directories

## Architecture Benefits
- **Complete Observability**: Automatic Logfire instrumentation + manual tracing + vault activity logs
- **Clean Separation**: Technical observability (Logfire) vs user activity logs (vault markdown)
- **Production Ready**: Robust vault context detection with comprehensive safety mechanisms
- **Zero Pollution**: No technical log files when Logfire disabled, clean vault-specific user logs

Phase 7 delivers a complete, production-safe logging architecture providing rich observability for developers and clear activity tracking for end users.

---

## 2025-07-31 - Renamed to changelog.py

**Simplified filename for better usability**

---

## 2025-07-31 - Test Minimal CLI (Phase 6)

**Testing the new minimal CLI interface**

---

## 2025-07-31 - Test Without Sys Path

**Testing import without sys.path manipulation**

---

## 2025-07-31 - Test UV Run Strategy (Phase 5)

**Testing UV run with inline Python code**

### Changes Made:
- **UV Integration**: Updated Claude instructions to use uv run  
- **Simplified Workflow**: No more import path issues
- **Single Command**: Everything in one uv run call

### Benefits:
- **No Import Hassles**: UV handles the environment setup
- **Clean Execution**: Single command for LLM to run
- **Consistent Environment**: Always uses project dependencies

---

## 2025-07-31 - Test Auto Init

Database should be created automatically

---

## 2025-07-31 - Test Minimal Implementation

**Created simplified changelog interface**

Replaced overengineered system with basic SQL functions.

---

## 2025-07-31 - Structured Changelog Entry Interface

**Implemented structured data model for consistent changelog entry formatting**

### Changes Made:
- **ChangelogEntryData Model**: Added structured data class with title, description, and details fields
- **Structured CLI Interface**: Updated add command to use title/description/details parameters
- **Automatic Markdown Generation**: Structured data converts to consistent markdown format
- **Updated Documentation**: Modified Claude commands to show new structured format

### Benefits:
- **Consistent Formatting**: All entries follow the same structure automatically
- **LLM-Friendly**: Clear expectations for AI systems creating changelog entries
- **Maintainable**: Structured data enables future enhancements and validation
- **Professional Output**: Generated markdown follows consistent patterns

### Files Modified:
- `scripts/changelog_manager.py` - Added ChangelogEntryData model and structured entry method
- `scripts/changelog_cli.py` - Updated CLI to use structured parameters
- `.claude/commands/document.md` - Updated documentation with new interface

---

## 2025-07-31 - Changelog Configuration Centralization

**Centralized configuration management to eliminate hardcoded paths throughout changelog scripts**

### Changes Made:
- **Configuration Module**: Created `scripts/changelog_config.py` with centralized path definitions and category mappings
- **Eliminated Hardcoded Paths**: Removed scattered path literals across all changelog scripts  
- **Configurable Categories**: Moved category keyword mappings to central configuration for easy maintenance
- **Dynamic Help Text**: CLI help messages now show actual configured paths instead of hardcoded examples

### Benefits:
- **Single Source of Truth**: All paths defined in one location for easy modification
- **Maintainable**: Changes to file locations require updates in only one place
- **Consistent**: All scripts use the same path configuration automatically
- **Flexible**: Easy to change root directory or reorganize file structure

### Files Modified:
- `scripts/changelog_config.py` - New centralized configuration module
- `scripts/changelog_manager.py` - Updated to use config constants
- `scripts/migrate_changelog.py` - Updated paths and moved category logic to config
- `scripts/export_changelog.py` - Updated to use centralized paths
- `scripts/changelog_cli.py` - Updated database path configuration

---

## 2025-07-31 - Changelog Database Migration Implementation (Phases 1-4)

**Completed changelog database migration system with SQLite backend and markdown export capabilities**

### New Components:
- **ChangelogManager**: SQLite-backed changelog storage with structured querying
- **Migration Script**: Automated parsing and migration of existing changelog.md entries  
- **Export Script**: Markdown generation from database maintaining human-readable format
- **CLI Tool**: Command-line interface for adding, querying, and managing entries

### Benefits:
- **Queryable**: Filter by category, date range, status, and phases
- **Structured**: Programmatic access to entry metadata and content
- **Maintainable**: Human-readable exports preserve existing workflow
- **Extensible**: Foundation for advanced reporting and analytics

---

## 2025-07-31 - @run-on Directive Completion (Phases 3-4)

**Completed Phases 3-4 of @run-on directive feature: Comprehensive validation framework and user documentation**

### Phase 3 - Validation Scenarios ✅
- **Focused Validation Scenario**: Created `run_on_directive_validation.py` with comprehensive end-to-end testing of @run-on functionality
- **Date Mocking Strategy**: Implemented proper date mocking to test different days without calendar dependencies using `patch('workflows.weekly_daily_journal.workflow.datetime')`
- **TestModel Integration**: Successfully integrated TestModel for fast, predictable validation (0.85s execution vs 8+ seconds with real LLM)
- **Evidence-Based Testing**: Generated observable artifacts in isolated runs with complete step execution verification
- **Multiple Day Scenarios**: Validated Monday (both steps), Tuesday-Wednesday (step2 only), Saturday (no steps) execution patterns

### Phase 4 - Documentation & Polish ✅
- **Template Enhancement**: Updated `sample-assistant.md` with practical @run-on examples showing `@run-on monday` for weekly planning and `@run-on monday, tuesday, wednesday, thursday, friday` for daily tasks
- **Comprehensive User Documentation**: Added dedicated "Step Scheduling with @run-on" section to `WELCOME.md` with:
  - Basic usage examples and syntax patterns
  - Supported day formats (full names, abbreviations, case-insensitive)
  - Common scheduling patterns (weekly + daily split, weekly review)
  - Updated example workflow explaining new step execution behavior
- **Feature Discoverability**: New vaults created with `launcher create` now demonstrate @run-on usage immediately
- **Error Handling Verification**: Confirmed existing `InvalidDirectiveError` system provides clear feedback for invalid day names

### Validation Results:
- ✅ **100% Test Success Rate**: All 4 day scenarios passed (Monday: both steps, Tuesday-Wednesday: step2 only, Saturday: no steps)
- ✅ **Fast Execution**: TestModel validation completes in 0.85s vs 8+ seconds with real LLM calls
- ✅ **Observable Evidence**: Generated step execution artifacts clearly demonstrate conditional behavior
- ✅ **Backward Compatibility**: Steps without @run-on continue using existing behavior seamlessly
- ✅ **User Experience**: Template demonstrates realistic usage patterns for immediate adoption

### TestModel Validation Pattern:
```python
# Key insight: Mock at workflow level, not core level
with patch('workflows.weekly_daily_journal.workflow.create_agent') as mock_create_agent:
    async def create_test_agent(*args, **kwargs):
        return await original_create_agent(*args, **kwargs, model_type='test')
    mock_create_agent.side_effect = create_test_agent
```

### Template Examples:
```markdown
## STEP1
@run-on monday
@output-file planning/{this-week}
Generate weekly priorities...

## STEP2  
@run-on monday, tuesday, wednesday, thursday, friday
@output-file daily/{today}
Generate daily tasks...
```

### Files Modified:
- `validation/scenarios/run_on_directive_validation.py` - Comprehensive @run-on validation scenario
- `validation/scenarios/test_model_validation.py` - TestModel validation helper
- `workflows/weekly_daily_journal/templates/vault/assistants/sample-assistant.md` - Added practical @run-on usage examples
- `workflows/weekly_daily_journal/templates/vault/WELCOME.md` - Added comprehensive step scheduling documentation

### Impact:
- **Complete Feature**: @run-on directive fully implemented, validated, and documented across all 4 phases
- **User Ready**: Feature discoverable through templates with clear documentation and working examples
- **Production Quality**: Comprehensive validation ensures reliability and proper error handling
- **Maintainable**: Clean validation patterns established for future directive development

**Status**: ✅ **FEATURE FULLY COMPLETE** - @run-on directive ready for production use with comprehensive validation and user documentation.

---

## 2025-07-30 - @run-on Directive Implementation (Phases 1-2)

**Completed Phases 1-2 of @run-on directive feature: Core directive processor and workflow day evaluation logic**

### Phase 1 - Core Directive Processor ✅
- **New RunOnDirective Class**: Implemented `@run-on` directive processor in `core/builtin_directives.py` following established patterns
- **Day Name Parsing**: Support for full day names (`monday`, `friday`) and abbreviations (`mon`, `fri`) with case-insensitive matching
- **Multi-Day Support**: Comma-separated day lists (`@run-on mon, wed, fri`) processed into clean `List[str]` for efficient workflow checking
- **Registry Integration**: Auto-registered with global directive registry, seamlessly integrated with existing `@output-file` and `@input-file` processing
- **Comprehensive Validation**: Proper error handling for invalid day names with informative error messages

### Phase 2 - Workflow Day Evaluation Logic ✅
- **Inline Day Checking**: Added simple, efficient day evaluation logic directly in `weekly_daily_journal` workflow loop
- **@run-on Priority**: Steps with `@run-on` directive use day-based execution, overriding default first-step behavior
- **Backward Compatibility**: Steps without `@run-on` preserve existing behavior (first step: week_start_day logic, subsequent steps: daily)
- **Recovery Behavior Configurable**: Added `ENABLE_FIRST_STEP_RECOVERY` flag for easy toggling of file-missing recovery logic
- **Consistent Recovery Logic**: Recovery behavior applies uniformly regardless of `@run-on` presence for predictable operation

### Technical Implementation:
```markdown
## STEP1
@run-on sunday
@output-file planning/{this-week}
Generate weekly priorities.

## STEP2  
@run-on monday, tuesday, wednesday, thursday, friday
@output-file daily/{today}
Generate daily tasks.
```

### New Directive Syntax:
- `@run-on monday` - Single day execution
- `@run-on mon, wed, fri` - Multiple days with abbreviations  
- `@run-on Sunday, FRIDAY` - Case-insensitive matching
- Steps without `@run-on` - Use existing week_start_day + recovery behavior

### Key Features:
- **Clean Architecture**: Core system parses, workflow decides execution (proper separation of concerns)
- **Efficient Processing**: `List[str]` return format enables simple `if today_name in run_on_days` checks
- **Recovery Control**: `ENABLE_FIRST_STEP_RECOVERY = True/False` flag provides easy behavior control
- **No Breaking Changes**: Existing assistants continue working exactly as before
- **Extensible Design**: Other workflows can interpret `@run-on` differently or ignore entirely

### Validation Results:
- ✅ Day matching works correctly (full names, abbreviations, case-insensitive)
- ✅ Multi-day specifications function properly
- ✅ Step skipping operates as expected with `continue` statement
- ✅ Integration with existing directives seamless
- ✅ Backward compatibility fully maintained
- ✅ Recovery behavior configurable and consistent

### Files Modified:
- `core/builtin_directives.py` - Added `RunOnDirective` class with registration
- `workflows/weekly_daily_journal/workflow.py` - Added inline day checking logic with configurable recovery

### Impact:
- **User Control**: Users can now specify exactly when workflow steps execute
- **Organized Output**: Different steps can target different files on appropriate days
- **System Reliability**: Recovery behavior ensures robustness while remaining configurable
- **Implementation Foundation**: Architecture ready for Phase 3 validation scenarios

**Status**: ✅ **FEATURE COMPLETE (Phases 1-2)** - @run-on directive core functionality implemented and tested, ready for validation framework integration.

---

## 2025-07-29 - Weekly Planning First Step Fix

**Fixed weekly planning workflow bug where first step ran every day instead of once per week**

### Problem Fixed:
- **Original Issue**: First step of weekly planning workflow was executing on every scheduled run, causing duplicate weekly priorities and excessive content generation
- **User Impact**: Weekly planning files were being recreated daily instead of only when needed

### Solution Implemented:
- **Conditional First Step Logic**: Modified `workflows/weekly_daily_journal/workflow.py` to add conditional execution for the first workflow step
- **Business Rule**: First step now only runs if it's the configured `week_start_day` OR if the output file doesn't exist yet
- **Preservation of Existing Behavior**: All subsequent steps continue running every day as intended

### Technical Implementation:
```python
# For first step, only run if it's week start day or output file doesn't exist
if i == 0:  # First step
    if today.weekday() != week_start_day and os.path.exists(output_file):
        logger.info(f"Skipping {step_name} (not week start day and file exists): {output_file_path}.md", 
                   local_logging=True, step_name=step_name, output_file=output_file_path)
        continue
```

### Expected Behavior:
- **Weekly Planning**: First step runs once per week on the configured week start day (e.g., Sunday)
- **Daily Tasks**: Subsequent steps continue running every day for daily task generation
- **Recovery Logic**: If weekly file is missing on any day, first step will run to recreate it
- **No Duplication**: Eliminates unnecessary regeneration of weekly content

### Files Modified:
- `workflows/weekly_daily_journal/workflow.py` - Added conditional execution logic for first step

**Status**: ✅ **BUG FIXED** - Weekly planning workflow now properly executes first step only when needed, eliminating content duplication while preserving recovery capability.

---

## 2025-07-27 - Simplified Logging Architecture Foundation (Phases 1-3)

**Completed first three phases of simplified logging architecture refactor: Foundation implementation, native Logfire integration, and vault context detection system**

### Phase 1: Core Logger Module Foundation ✅ **COMPLETED**

**New Module Structure**: Created `core/logger/` module replacing dual-purpose `UnifiedLogger` with simplified architecture:

- **`core/logger/logger.py`**: Simplified `UnifiedLogger` with direct Logfire integration and vault-aware activity logging
- **`core/logger/vault_context.py`**: Automatic vault context detection from function parameters (global_id, vault_path, file_path patterns)
- **`core/logger/vault_writer.py`**: Vault log writing functions for user-facing activity logs in markdown format
- **Clean Separation**: Technical observability (Logfire only) completely separated from user activity logging (vault markdown)

### Phase 2: Native Logfire Integration ✅ **COMPLETED**

**Maximum Data Collection Through Native Capabilities**: Enhanced decorator implementation to leverage Logfire's native instrumentation:

- **Native `@logfire.instrument`**: Replaced custom decorator with thin wrapper around native Logfire implementation for maximum data richness
- **Template Span Names**: Support for dynamic span names like `"Processing {vault=} workflow {step=}"`
- **Selective Argument Extraction**: `extract_args=['vault_path']` for filtering large objects or sensitive data
- **Return Value Capture**: `record_return=True` captures actual return values and timing information
- **Automatic Exception Tracking**: Native decorator captures stack traces and error details automatically
- **Zero Overhead**: When `ENABLE_LOGFIRE=false`, decorators return original functions unmodified

### Phase 3: Comprehensive Automatic Instrumentation ✅ **COMPLETED**

**Rich Technical Observability Without Explicit Logging**: Implemented comprehensive automatic instrumentation system:

- **FastAPI**: All HTTP requests, responses, route parameters, and status codes traced automatically
- **Pydantic-AI**: Agent runs, model calls, tool execution, and conversation flows captured with full context
- **Pydantic**: Model validation, serialization, and field errors instrumented automatically
- **APScheduler**: Job lifecycle events through Python logging instrumentation integration
- **Environment Control**: `ENABLE_LOGFIRE=false` provides zero technical logging overhead in production

### Phase 3: Vault Context Detection System ✅ **COMPLETED**

**Automatic User Activity Logging**: Implemented vault-aware logging with automatic context detection:

- **Auto-Context Detection**: Vault context automatically detected from `global_id` (`TestVault/assistant`), `vault_path` (`/app/data/TestVault`), and file path patterns
- **New Log Locations**: User activity logs written to `{vault}/assistants/logs/{assistant}.md` instead of mixed system/vault locations
- **Simplified API**: `logger.vault_log("message")` with automatic vault detection eliminates complex parameter passing
- **Rich Context**: Extra parameters automatically included in log entries for enhanced user visibility

### Architectural Improvements:

**Thin Wrapper Design**: `UnifiedLogger` now serves as intelligent thin wrapper around native Logfire:
- **Direct Delegation**: Technical logging methods (`info`, `error`, `span`) directly delegate to Logfire when enabled
- **Native API Compatibility**: Developers learn one interface that matches Logfire exactly
- **Automatic Tag Prefixing**: Span names automatically prefixed with module tags (`"workflow:operation"`)
- **Clean When Disabled**: Zero performance impact when Logfire disabled

**Developer Experience Enhancements**:
- **Single Import**: `logger = UnifiedLogger(tag="module")` provides consistent interface across codebase
- **Rich Decorators**: `@logger.instrument()` and `@logger.trace()` provide maximum observability with minimal code
- **Automatic Instrumentation**: `logger.setup_instrumentation(app)` enables comprehensive system tracing
- **Vault-Aware Logging**: `logger.vault_log()` provides user-visible activity tracking

### Documentation Updates:

**Architecture Documentation**: Updated `/app/docs/architecture.md` with comprehensive new section covering:
- **Technical Observability**: Automatic instrumentation capabilities and manual decoration patterns
- **User Activity Logging**: Vault-aware logging with auto-context detection examples
- **Developer Integration**: Module-level setup patterns and application configuration examples

**User Documentation**: Updated `/app/README.md` to reflect new logging architecture:
- **Activity Monitoring**: Updated to new vault log locations `{vault}/assistants/logs/{assistant}.md`
- **Developer Debugging**: Simplified explanation of `ENABLE_LOGFIRE=true` for technical traces
- **User-Focused**: Removed technical details while maintaining clear guidance

### Git Repository Management:

**Validation Runs Cleanup**: Implemented `.gitignore` rules for `validation/runs/` directory:
- **Directory Preserved**: `validation/runs/` directory visible in repository via `.gitkeep` file
- **Contents Ignored**: All validation run outputs automatically ignored (`validation/runs/*`)
- **Clean Commits**: No manual cleanup required after validation runs

### Implementation Plan Updates:

**Refined Migration Strategy**: Updated implementation plan to reflect "strip down, verify foundation, build back up" approach:
- **Phase 4**: Complete logging removal and import migration - eliminate ALL manual logging calls
- **Phase 5**: Automatic instrumentation validation - verify FastAPI, Pydantic-AI, Pydantic traces
- **Phase 6**: APScheduler integration - ensure scheduler events visible in Logfire
- **Phase 7**: Selective manual addition - strategically add decorators and vault logs where needed

### Technical Foundation Established:

**Key Benefits Achieved**:
- **Maximum Data Collection**: Native Logfire integration captures more data with less code than custom implementation
- **Clean Architecture**: Complete separation between technical observability and user activity logging
- **Developer Simplicity**: Single logger interface that works consistently across all modules
- **Environment Control**: Zero technical logging pollution when Logfire disabled
- **User Transparency**: Activity logs automatically appear in vault directories without configuration

**Status**: ✅ **SIMPLIFIED LOGGING FOUNDATION COMPLETE** - Core architecture established with native Logfire integration, automatic instrumentation, and vault-aware activity logging. Ready for systematic module migration in remaining phases.

---

## 2025-07-25 - Validation Framework Evolution & System Bug Discovery

**Comprehensive enhancement of the evidence-based validation framework with fault-tolerant execution, central issue tracking, and discovery of critical system bug in directive registration.**

### Major Framework Enhancements:

#### Central Issues Logging System
- **Automatic Issue Tracking**: Added `issues_log.md` at validation root to centrally track all problems requiring action
- **Smart Classification**: Issues automatically categorized as System Errors (🚨 HIGH), Framework Errors (💥 MEDIUM), Validation Failures (❌ MEDIUM), or Unexpected Errors (❓ MEDIUM)
- **Actionable Reporting**: Each entry includes timestamp, run ID links, severity level, error description, and specific recommendations
- **Selective Logging**: Only logs issues requiring action (system bugs, framework errors, validation failures) - successful scenarios ignored

#### Strategic Error Handling & Fault Tolerance
- **Comprehensive Assessment**: Implemented strategic try/catch blocks in all scenarios to ensure complete validation runs regardless of individual step failures
- **Step-Level Isolation**: Each validation step captures its own errors while continuing execution of remaining steps
- **Rich Evidence Collection**: Failure scenarios still generate complete evidence files with error context (error type, message, stack traces)
- **Complete System Picture**: Can now distinguish between isolated issues vs systemic problems by seeing which components work vs fail

#### Self-Contained Run Architecture
- **Isolated Execution**: Each run creates completely independent environment with unique timestamped directories
- **Standardized Structure**: All runs use consistent `vaults/` subdirectory for predictable, clean organization
- **Template Integration**: Leverages existing workflow templates instead of duplicating test content
- **Enhanced Summaries**: Run summaries include narrative step-by-step flow with evidence links and actionable outcomes

### Phase 4 Scenario Implementation:

#### Content Processing Validation (`content_processing.py`)
- **Input File Directives**: Validates `@input-file` processing with real file content injection
- **Time Pattern Resolution**: Tests `@latest`, `@latest:N`, `@this-week` pattern resolution against historical journal entries
- **Output File Directives**: Validates `@output-file` directive parsing and directory structure creation
- **Missing File Handling**: Tests graceful handling of references to non-existent files

#### Workflow Execution Validation (`workflow_execution.py`)  
- **End-to-End Execution**: Complete 4-step workflow execution with AI mocking and file generation
- **Multi-Step Coherence**: Analyzes workflow steps for logical context building and output relationships
- **Output Organization**: Validates proper file organization in structured directories (planning/, daily/, journal/)
- **Configuration Integration**: Tests assistant configuration loading and schedule parsing integration

#### Enhanced AI Mocking System
- **Workflow-Specific Responses**: Updated mock templates with realistic weekly planning, task breakdown, time blocking, and blocker analysis content
- **Context-Aware Patterns**: Mock responses tailored to validation scenarios while remaining generic enough for framework reuse
- **Runtime Configuration**: Environment variable controls (`VALIDATION_USE_MOCK_AI`) for switching between mocked and real AI responses

### Critical System Bug Discovery & Resolution:

#### Directive Registration Bug (🚨 HIGH SEVERITY)
- **Issue Discovered**: Validation framework revealed that `@output-file` and `@input-file` directives were not being registered at runtime
- **Root Cause**: `core/builtin_directives.py` module was not being imported in `core/step_processor.py`, so auto-registration never occurred
- **Symptom**: `InvalidDirectiveError: Unknown directive: 'output-file'. Registered directives: []` - completely empty directive registry
- **Impact**: Workflow execution failing with directive errors in production
- **Resolution**: Added `import core.builtin_directives` to `step_processor.py` to ensure directive registration occurs before processing
- **Validation**: Confirmed fix with successful end-to-end workflow execution generating 3 output files across 4 workflow steps

### Architecture Documentation & Guidelines:

#### Updated Validation README
- **Core Framework Principles**: Clear separation between generic core components (never modify) and business-specific scenarios (all domain logic)
- **Development Guidelines**: Comprehensive guidance for strategic error handling, complete isolation, and comprehensive testing practices
- **Usage Documentation**: Complete CLI examples, result review processes, and scenario development templates
- **Architecture Overview**: Detailed explanation of self-contained runs, central issues log, and error classification system

#### Local Logging Architecture Analysis
- **Architectural Gap Identified**: System-level operations (config loading) that discover vault-specific errors don't automatically create local logs in vault directories
- **Issue Documented**: Created `/app/docs/local-logging-architecture-notes.md` explaining the problem and potential solutions
- **Design Decision**: Recognized this as broader architectural question requiring system-level resolution rather than validation framework patches

### Scenario Evolution & Error Handling:

#### All Scenarios Enhanced with Strategic Error Handling
- **`edge_cases.py`**: Empty vault handling, malformed configuration processing, invalid schedule rejection with user guidance
- **`system_setup.py`**: Core module imports, configuration manager initialization, vault discovery functionality  
- **`api_health.py`**: CLI launcher testing, API endpoint validation, configuration integration checks
- **Fault Isolation**: Each scenario now tests all functionality areas even when individual steps fail, providing comprehensive system assessment

### Framework Maturity Achievements:

- **Production Bug Discovery**: Successfully identified and resolved real production issue through validation execution
- **Comprehensive Coverage**: 5 scenarios validating system setup, API health, edge cases, content processing, and workflow execution
- **100% Success Rate**: All scenarios pass with strategic error handling ensuring complete validation runs
- **Evidence-Based Confidence**: Generated artifacts, step-by-step summaries, and issue tracking provide clear system health assessment
- **Developer-Friendly**: Clear documentation, development guidelines, and separation of concerns enable easy scenario development

### Technical Implementations:

#### New Files Created:
- **`validation/issues_log.md`** - Central issue tracking log with automated severity classification
- **`validation/scenarios/content_processing.py`** - Directive processing and file operations validation
- **`validation/scenarios/workflow_execution.py`** - End-to-end workflow execution validation  
- **`docs/local-logging-architecture-notes.md`** - Analysis of logging architecture gaps and solutions

#### Files Enhanced:
- **`validation/core/runner.py`** - Added central issue logging, enhanced run summaries, step tracking integration
- **`validation/core/ai_mocker.py`** - Workflow-specific response templates, enhanced mock patterns
- **`validation/scenarios/edge_cases.py`** - Strategic error handling, comprehensive step coverage
- **`validation/scenarios/system_setup.py`** - Fault-tolerant testing with detailed step tracking
- **`validation/scenarios/api_health.py`** - Enhanced error handling and evidence collection
- **`validation/README.md`** - Complete rewrite with current architecture, development guidelines, and usage documentation

#### Critical Bug Fix:
- **`core/step_processor.py`** - Added `import core.builtin_directives` to ensure directive registration occurs before processing

### Validation Framework Status:
✅ **VALIDATION FRAMEWORK EVOLUTION COMPLETE** - Transformed from basic scenario execution to comprehensive, fault-tolerant system validation platform with central issue tracking, strategic error handling, and proven ability to discover and resolve real production bugs. Framework now provides complete separation of concerns between generic core and business logic while ensuring thorough system assessment regardless of individual component failures.

---

## 2025-07-25 - Parameter Processing Refactor Complete (Phases 5-6)

**Completed final phases of parameter processing refactor: Architectural separation, workflow integration audit, and deprecated code cleanup**

### Phase 5: Architectural Separation & Integration ✅ **COMPLETED**

**Core Architectural Achievement**: Established clean separation between configuration management and workflow execution systems:

- **Configuration System Isolation**: `AssistantConfigManager` now focuses purely on vault discovery, assistant file parsing, and scheduler job setup
- **Self-Contained Workflows**: Workflows read and process their own assistant files at runtime with current date context, eliminating configuration dependencies
- **Immutable Parameter Passing**: Scheduler passes only needed parameters (`vault_path`, `assistant_file_path`, `week_start_day`, `global_id`) instead of mutable `AssistantConfig` objects
- **Runtime Directive Processing**: All `@input-file` and `@output-file` directives processed when workflow actually executes, ensuring time patterns resolve correctly

### Phase 4 Audit: Workflow Integration Review ✅ **COMPLETED**

**Comprehensive audit of workflow integration confirmed all design decisions**:

- **Input File Content Assembly**: Structured metadata from `InputFileDirective` properly normalized and formatted for LLM consumption
- **List-of-Lists Handling**: Multiple `@input-file` directives correctly flattened at workflow level while preserving directive processor separation
- **File Headers**: Content formatted with complete filepath headers (`journal/2025-07-24`) for clear LLM context
- **Error Handling**: Missing files handled gracefully with placeholder text, maintaining workflow execution
- **Clean Abstraction**: Workflow policy decisions (formatting, defaults, error handling) properly separated from core directive processing

### Phase 6: Cleanup & Deprecated Code Removal ✅ **COMPLETED**

**Complete removal of old parameter processing system**:

- **Deprecated Modules Deleted**: Removed `/app/core/parameter_extraction.py` and `/app/core/prompt_file_injection.py` along with associated test files
- **Clean References**: Updated comments in `builtin_directives.py` to remove references to deleted modules
- **Import Verification**: Confirmed no remaining imports of deprecated modules in active codebase
- **Application Verification**: Tested core directive processing and application startup without deprecated modules

### Technical Implementation Summary:

**Complete Refactor Achievement**: Successfully transitioned from hardcoded parameter processing to extensible registry-based directive system:

- **Registry Foundation**: `DirectiveProcessorRegistry` with auto-registration enables adding new directive types without core changes
- **Built-in Processors**: `OutputFileDirective` and `InputFileDirective` handle common workflow operations with time pattern resolution
- **Step Processing Orchestration**: `process_step_content()` coordinates parsing, processing, and result aggregation with clean abstraction
- **Workflow Flexibility**: Individual workflows control all policy decisions about directive usage, defaults, and content formatting

### Breaking Changes & Migration:
- **No User Impact**: Sample assistant templates already used new directive syntax
- **Clean Codebase**: All deprecated parameter processing code removed
- **Preserved Functionality**: All existing `@input-file` and `@output-file` capabilities maintained through new system

### Files Modified:
- **Deleted**: `/app/core/parameter_extraction.py`, `/app/core/prompt_file_injection.py`, `/app/tests/test_parameter_extraction.py`
- **Updated**: `/app/core/builtin_directives.py` - Removed reference to deleted file
- **Verified**: Application startup and core directive processing functionality

**Status**: ✅ **PARAMETER PROCESSING REFACTOR COMPLETE** - Six-phase refactor successfully completed, establishing extensible directive processing foundation while maintaining all existing functionality and enabling future workflow system enhancements.

---

## 2025-07-24 - Step Processing Orchestration and Workflow Abstraction (Phase 4)

**Completed Phase 4 of parameter processing refactor: Full orchestration implementation with clean abstraction between core processing and workflow-specific decisions**

### Core Implementation:
- **Complete Orchestration Logic**: Implemented full `process_step_content()` function coordinating directive parsing, registry processing, and result aggregation
- **Context Propagation**: Reference dates and week start days properly passed through to directive processors for accurate time pattern resolution
- **Generic Result Interface**: Replaced directive-specific helper methods with generic `get_directive_value()` accessor for complete workflow flexibility
- **Comprehensive Error Handling**: Full validation and error reporting across directive parsing, processing, and orchestration layers

### Architectural Decision - Clean Abstraction:
- **Core Remains Abstract**: `process_step_content()` performs pure orchestration without workflow-specific assumptions or defaults
- **Workflow Controls Policy**: Individual workflows decide how to handle missing directives, apply defaults, and process directive results
- **Clear Responsibility Separation**: Core handles mechanics (parsing, registry lookup, processing), workflows handle policy (defaults, formatting, error handling)
- **Extensible Design**: New workflows can use different directive types, default behaviors, and data handling strategies without core changes

### Key Refactoring:
- **Removed Workflow-Specific Defaults**: Eliminated hardcoded `'journal/{this-week}'` pattern from core processor
- **Eliminated Directive-Specific Helpers**: Replaced `get_output_file_path()` and `get_input_file_content()` with generic interface
- **Workflow-Level Normalization**: Moved input file list-of-lists flattening logic to workflow where data handling decisions belong
- **Context-Aware Processing**: Built-in directive processors now receive and use reference dates and configuration parameters

### Updated Workflow Integration:
- **`weekly_daily_journal/workflow.py`**: Updated to handle own defaults, flatten input files, and format content for AI agents
- **Policy Visibility**: All decisions about how to use step data are clearly visible in workflow implementation
- **Flexible Data Handling**: Workflow demonstrates proper normalization of directive results while maintaining clean separation

### Testing Coverage:
- **Step Processor Tests**: 16 comprehensive test cases covering orchestration logic, error handling, and edge cases
- **Integration Verification**: End-to-end workflow integration confirmed working with new abstract interface
- **Generic Interface Testing**: All tests updated to use generic `get_directive_value()` method instead of directive-specific helpers

### Impact and Benefits:
- **Clear Architectural Boundaries**: Developers can easily understand what decisions are made in core vs. workflow layers
- **Easily Changeable Decisions**: Workflow-specific behaviors can be modified without touching core processing logic
- **Workflow Extensibility**: New workflows can implement completely different approaches to directive handling and data processing
- **Maintainable Abstraction**: Core processing remains stable while workflows evolve independently

### Files Modified:
- `/app/core/step_processor.py` - Complete orchestration implementation with generic interface (183 lines)
- `/app/workflows/weekly_daily_journal/workflow.py` - Updated workflow integration with policy handling (185 lines)
- `/app/tests/test_step_processor.py` - Comprehensive orchestration tests (420 lines)

This phase completes the parameter processing refactor by establishing a clean architectural boundary where the core system provides abstract directive processing capabilities while workflows retain full control over how directive results are interpreted, formatted, and used. The design ensures that all policy decisions about step data usage are visible and easily modifiable in workflow implementations.

---

## 2025-07-24 - Built-in Directive Processors Implementation (Phase 3)

**Completed Phase 3 of parameter processing refactor: Registry-based directive processing system with built-in processors for @output-file and @input-file**

### Core Implementation:
- **Registry-Based Architecture**: Implemented `DirectiveProcessorRegistry` with auto-registration system for modular directive processing
- **Built-in Processors**: Created `OutputFileDirective` and `InputFileDirective` processors with comprehensive parameter parsing and validation
- **Structured Metadata Output**: InputFileDirective now returns structured metadata dictionaries instead of formatted strings for better data flow
- **File Loading Utilities**: Added `load_file_safely()` and `load_files_from_paths()` utilities with robust error handling and encoding detection

### New Components Added:
- **`core/directive_parser.py`**: Core parsing engine with `DirectiveParser` class for extracting and processing directives from text
- **`core/parameter_registry.py`**: Registry system with auto-discovery and validation of directive processors
- **`core/step_processor.py`**: High-level step processing interface integrating directive parsing with file operations
- **Built-in Directive Classes**: Complete processor implementations with parameter validation and comprehensive documentation

### Key Architectural Changes:
- **Breaking Change**: `InputFileDirective.process()` now returns structured metadata dictionaries `{'file_path': str, 'content': str, 'metadata': dict}` instead of formatted strings
- **Auto-Registration**: Directive processors automatically register themselves using `@register_directive_processor` decorator
- **Extensible Design**: Clean interface for adding new directive types without modifying core parsing logic
- **Enhanced Error Handling**: Comprehensive validation with informative error messages for malformed directives

### Technical Implementation:
- **Pattern-Based Processing**: Integrates with existing pattern resolution system for time-based file paths
- **Vault-Aware Operations**: All file operations respect vault boundaries and use absolute path resolution
- **Test-Driven Development**: Comprehensive test coverage with 45+ test cases covering all directive scenarios
- **Memory Efficient**: Processes directives in-place without creating unnecessary data copies

### New Directive Syntax Support:
```markdown
@output-file planning/{today}
@input-file goals.md
@input-file journal/{latest:3}
@input-file notes/{this-week}
```

### Testing Coverage:
- **DirectiveParser Tests**: 15 tests covering parsing, extraction, and error handling
- **Parameter Registry Tests**: 12 tests covering registration, validation, and processor discovery
- **Step Processor Integration Tests**: 18 tests covering end-to-end directive processing workflows
- **File Loading Utility Tests**: Comprehensive testing of encoding detection and error scenarios

### Impact and Foundation:
- **Registry System Complete**: Foundation established for replacing hardcoded parameter system throughout codebase
- **Modular Architecture**: New directive types can be added through simple processor classes
- **Enhanced Data Flow**: Structured metadata enables better integration with workflow systems
- **Performance Optimized**: Efficient parsing with minimal overhead for directive-free content

### Files Added:
- `/app/core/directive_parser.py` - Core directive parsing engine (187 lines)
- `/app/core/parameter_registry.py` - Registry and auto-discovery system (143 lines)  
- `/app/core/step_processor.py` - High-level processing interface (98 lines)
- `/app/tests/test_directive_parser.py` - Comprehensive parser tests (542 lines)
- `/app/tests/test_parameter_registry.py` - Registry system tests (387 lines)

This implementation establishes the complete registry-based directive processing foundation, enabling future phases to systematically replace hardcoded parameter handling throughout the workflow system while maintaining backward compatibility and enhancing extensibility.

---

## 2025-07-22 - Critical Bug Fix: @input-file Parameter Processing

**Fixed critical bug preventing @input-file directives from working in assistant configurations**

### Bug Description:
The `@input-file` directives in assistant STEP sections were being stripped during configuration loading, preventing file content from being embedded into AI prompts. This broke a core feature that allows assistants to reference context files like goals, previous journal entries, and project notes.

### Root Cause:
In `core/assistant_config.py` line 864, the code was using `extraction_result.cleaned_text` which removes ALL parameter directives, including `@input-file`, not just `@output-file` as intended.

### Changes Made:
- **Fixed Parameter Preservation**: Modified `load_workflow_content()` to manually remove only `@output-file` lines while preserving `@input-file` lines in step prompts
- **Selective Cleaning**: Replaced generic parameter cleaning with targeted removal of only `@output-file` directives
- **Maintained Functionality**: All existing `@output-file` processing continues to work correctly

### Impact:
- ✅ **@input-file directives now work correctly** - assistants can reference context files
- ✅ **File embedding restored** - content from referenced files appears in AI prompts
- ✅ **Pattern support functional** - time-based patterns like `{latest}`, `{latest:3}` work as designed
- ✅ **No breaking changes** - all existing functionality preserved

### Technical Details:
- **File Modified**: `/app/core/assistant_config.py` lines 863-871
- **Testing**: Verified with existing end-to-end test `test_end_to_end_input_file_embedding`
- **Backward Compatibility**: Full - no user configuration changes required

This fix restores a critical feature that enables assistants to maintain context across planning sessions by referencing user's existing notes and files.

---

## 2025-07-20 - API Infrastructure and Vault Ignore System

### Added
- **API Infrastructure**: New REST API endpoints for system management and user onboarding
  - `GET /api/status` - Comprehensive system status with vault discovery, scheduler status, and system health
  - `POST /api/vaults/rescan` - Force immediate rediscovery and configuration reload (placeholder)
  - `POST /api/vaults/create` - Create template vault with sample configuration (placeholder)
  - Complete Pydantic models for request/response validation
  - Standardized error handling with proper HTTP status codes
  - FastAPI integration with existing application lifecycle

- **Vault Ignore System**: New `.vaultignore` mechanism to exclude directories from vault discovery
  - Simple presence-based ignore system following gitignore/dockerignore conventions
  - Automatic creation in system logs directory (`/app/data/logs`)
  - User-controlled exclusion of any directory by adding `.vaultignore` file
  - Resolves architectural issue where logs directories were incorrectly discovered as vaults

- **Enhanced Status Reporting**: Real-time system status collection and reporting
  - Live vault discovery with assistant counting
  - Scheduler integration showing job status and assistant counts
  - System health tracking (startup time, last config reload)
  - Graceful error handling with partial status reporting

### Changed
- **Vault Discovery**: Updated `discover_vaults()` to respect `.vaultignore` files
  - System logs directory now automatically excluded from vault discovery
  - Clear logging when directories are ignored
  - Maintains backward compatibility for existing vault structures

- **Logging System**: Enhanced LocalLogger to automatically create vault ignore files
  - System logs at `/app/data/logs` get `.vaultignore` automatically
  - Vault-specific logs remain discoverable within their vaults
  - Non-breaking addition to existing logging functionality

### Fixed
- **Vault Discovery Conflicts**: Resolved issue where system logs directory was treated as a vault
  - Status endpoints no longer report logs directory as a vault
  - Clean separation between system directories and user vaults
  - Improved reliability of vault counting and discovery

### Technical Improvements
- **API Architecture**: Clean separation with services layer, models, and endpoint handlers
- **Error Handling**: Comprehensive exception handling with informative error responses
- **Testing**: Extensive test coverage (36+ tests) for vault ignore, API services, and status integration
- **Path Safety**: Enhanced path validation and safety checks for vault operations

---

## [2025-07-21] - Phase 4b: Vault Creation Implementation

### Added
- **Vault Creation API Endpoint**: Complete implementation of `POST /api/vaults/create`
  - Creates template vault structures from workflow templates
  - Dynamic workflow template discovery from `workflows/{workflow}/templates/vault/`
  - Comprehensive conflict detection with proper HTTP 409 responses
  - Returns detailed creation statistics including file counts and assistant paths

- **Vault Creation Service**: New `create_vault_from_workflow_template()` function
  - Integrates with existing `create_vault_from_template()` core functionality
  - Validates vault existence and workflow template availability
  - Discovers and reports created files and assistant configurations
  - Robust error handling with specific exception types

- **Template-Based Vault Generation**: Full integration with Phase 4a template framework
  - Uses workflow-embedded templates from `workflows/{workflow}/templates/vault/`
  - Automatically copies complete directory structures
  - Preserves template file contents with light customization
  - Supports any workflow that provides template directory

### Enhanced
- **API Error Handling**: Enhanced error responses with proper HTTP status codes
  - 409 for vault conflicts (`VaultAlreadyExistsError`)
  - 400 for invalid vault names (`InvalidVaultNameError`)
  - 500 for file system errors (`FileSystemError`)
  - Detailed error messages with vault names and reasons

- **Testing Coverage**: Comprehensive test suite for vault creation functionality
  - Dynamic template discovery (no hardcoded file expectations)
  - Full integration testing of API endpoints
  - Conflict detection and error scenario testing
  - Template structure verification and file counting

### Technical Implementation
- **Service Layer**: Clean separation between API endpoints and business logic
- **Exception Handling**: Specific exception types for different failure modes
- **Path Safety**: Secure vault path construction within data root boundaries
- **Template Flexibility**: Future-proof design supporting multiple workflow types

### Breaking Changes
- None - All changes are additive to existing functionality

### Migration Notes
- Existing vaults and configurations remain unchanged
- No action required for existing installations
- New vault creation capability available immediately upon deployment

---

## [2025-07-22] - Critical @input-file Bug Fix

### Fixed
- **@input-file Directive Stripping Bug**: Restored ability for assistants to reference context files using `@input-file` directives in step prompts
  - **Root Cause**: Configuration loading was using `extraction_result.cleaned_text` which removes ALL parameter directives, including essential `@input-file` directives needed for file content embedding
  - **Solution**: Modified `/app/core/assistant_config.py` line 864 to manually remove only `@output-file` lines while preserving `@input-file` lines in step prompts
  - **Impact**: This fixes a core feature that allows assistants to embed content from vault files (goals, journal entries, etc.) into AI prompts for context-aware planning

### Technical Details
- **Bug Location**: `/app/core/assistant_config.py` in `load_workflow_content()` function
- **Previous Behavior**: `step_prompts[step_name] = extraction_result.cleaned_text.strip()` removed all directives
- **New Behavior**: Manual line-by-line filtering that only removes `@output-file` directives while preserving `@input-file` directives
- **Testing**: Existing end-to-end test `test_end_to_end_input_file_embedding` passes, confirming the fix restores file embedding functionality

### User Impact
- **Restored Functionality**: Users can now reference context files in assistant steps using directives like:
  - `@input-file goals.md` - Embed specific files
  - `@input-file journal/{latest:3}` - Embed recent journal entries
  - `@input-file notes/{this-week}` - Embed time-based file collections
- **No Breaking Changes**: All existing assistant configurations continue to work as before
- **Enhanced Context**: AI assistants now receive actual file content for context-aware planning and task generation

---

## [2025-07-21] - CLI Launcher and Documentation Improvements

### Added
- **CLI Launcher Script**: Complete command-line interface for Project Assistant management
  - `./launcher status` - Display system health with color-coded output
  - `./launcher rescan` - Trigger vault discovery and configuration reload
  - `./launcher create <name>` - Create new vaults from workflow templates
  - Built-in help system and comprehensive error handling
  - JSON formatting with `jq` integration and graceful fallback

- **Enhanced Setup Documentation**: Comprehensive installation guide with step-by-step instructions
  - Clear prerequisite requirements (Docker Engine, Gemini API key)
  - Detailed VAULTS_ROOT_PATH configuration with visual examples
  - Launcher executable setup instructions
  - Verification steps for successful installation

### Enhanced
- **User Experience**: CLI launcher provides much better UX than raw curl commands
  - Color-coded status indicators (green for healthy, red for errors)
  - Formatted output with clear section headers
  - Helpful error messages with troubleshooting guidance
  - Next-steps guidance after vault creation

- **Documentation Quality**: README now includes complete setup workflow
  - Docker installation links and prerequisites
  - Vault directory structure explanation with examples
  - CLI launcher usage examples prominently featured
  - API documentation maintained as alternative access method

### Technical Implementation
- **Bash Script Architecture**: Single executable script with command parsing
- **API Integration**: Robust error handling and timeout management
- **JSON Processing**: Dynamic `jq` detection with plain text fallback
- **Exit Codes**: Proper exit codes for scripting and automation

### Breaking Changes
- None - CLI launcher is purely additive functionality

### Migration Notes
- Run `chmod +x launcher` to make the script executable
- No changes required to existing configurations or workflows
- CLI launcher available immediately for improved system management

---

## 2025-07-20 - API Vault Rescan Endpoint Implementation (Phase 3)

**Completed Phase 3 of API implementation: POST /api/vaults/rescan endpoint for dynamic configuration reload**

### Changes Made:
- **Vault Rescan Endpoint**: Implemented `POST /api/vaults/rescan` for force reloading vault configurations and updating scheduler jobs
- **Reusable Scheduler Logic**: Extracted scheduler setup logic into `core/scheduler_utils.py` for consistency between startup and rescan
- **Dynamic Job Management**: Rescan removes existing scheduler jobs and recreates them based on current configurations
- **Comprehensive Testing**: Added 8 new test cases in `tests/test_rescan_functionality.py` covering all rescan scenarios
- **Error Resilience**: Graceful handling of individual assistant failures during rescan operations

### Technical Details:
- **New Module**: `core/scheduler_utils.py` with `setup_scheduler_jobs()` and `refresh_scheduler_jobs()` functions
- **Service Layer**: `rescan_vaults_and_update_scheduler()` in `api/services.py` handles complete rescan workflow
- **Endpoint Implementation**: Full replacement of placeholder rescan endpoint with production-ready functionality
- **Refactored Startup**: Updated `main.py` to use shared scheduler utilities ensuring identical behavior
- **Statistics Reporting**: Returns vault count, assistant counts, and scheduler job update counts

### API Response Format:
```json
{
  "success": true,
  "vaults_discovered": 3,
  "assistants_loaded": 7,
  "enabled_assistants": 5,
  "scheduler_jobs_updated": 5,
  "message": "Rescan completed successfully: 3 vaults, 5 enabled assistants, 5 jobs updated"
}
```

All 241 tests passing (including 8 new rescan tests). No breaking changes - fully backward compatible.

---

## 2025-07-20 - Workflow-Embedded Template Framework (Phase 4a)

**Completed Phase 4a: File-based vault template system with workflow-embedded templates**

### Changes Made:
- **Template Framework**: Implemented flexible template system where workflows provide their own templates in `workflows/{workflow}/templates/vault/`
- **File-based Templates**: Migrated from Python string-based templates to actual markdown files for better maintainability
- **Template Function**: Replaced `create_default_assistant()` with `create_vault_from_template()` that copies entire directory structures
- **Complete Vault Structure**: Template creates comprehensive vault with WELCOME.md, sample assistants, and example files
- **Fail-fast Design**: Raises clear errors if workflow doesn't provide templates (no backward compatibility fallbacks)

### Technical Details:
- **New Function**: `create_vault_from_template()` in `core/assistant_config.py` handles template directory copying
- **Template Location**: `workflows/weekly_daily_journal/templates/vault/` contains complete vault template structure
- **Content Customization**: Template files are lightly customized with vault name during creation
- **Manager Integration**: Updated `AssistantConfigManager.create_default_assistant()` to use new template system
- **Comprehensive Testing**: Added `TestVaultTemplateCreation` test class with 5 test cases covering all template scenarios

### Breaking Changes:
- **Function Removal**: `create_default_assistant()` function removed from `core/assistant_config.py`
- **Manager Behavior**: `AssistantConfigManager.create_default_assistant()` now creates full vault template instead of single assistant file
- **File Removal**: `workflows/weekly_daily_journal/defaults.py` deleted - content migrated to template files

### Template Structure Created:
- `WELCOME.md` - Comprehensive onboarding guide
- `assistants/sample-assistant.md` - 4-step assistant with realistic configuration
- `examples/` - Multiple example files demonstrating file embedding patterns
- Full directory structure preserved during template copying

---

## 2025-07-19 - Flexible Output File System Implementation

**Implemented comprehensive flexible output file system allowing workflow steps to write to different files with automatic directory creation**

### Major Features Implemented:
- **Per-Step Output Files**: Each workflow step can now specify custom output files using `@output-file path/pattern` directives
- **Pattern-Based Paths**: Support for time-based patterns like `@output-file planning/{this-week}` and `@output-file daily/{today}`
- **Multi-File Workflows**: Single workflow can create multiple output files in different directories during one execution
- **Automatic Directory Creation**: System creates nested directories automatically (e.g., `planning/goals/2024/` created from `planning/goals/{this-year}`)
- **Auto-Injection Defaults**: Steps without explicit `@output-file` get sensible default `journal/{this-week}` pattern

### Core Components Added:
- **`WorkflowContent.step_output_files`**: New field storing `{step_name: output_pattern}` mappings extracted from `@output-file` parameters
- **Enhanced Parameter Extraction**: `load_workflow_content()` now extracts and removes `@output-file` directives from step content
- **Per-Step File Resolution**: `workflow.py` resolves output patterns for each step individually using `resolve_time_pattern_to_single()`
- **Multi-File Handling Logic**: Tracks created files during workflow runs to handle append vs create logic per unique file

### Technical Implementation:
- **Pattern Resolution Enhancement**: Enhanced `resolve_time_pattern_to_single()` to handle path templates like `journal/{this-week}` and `planning/{today}/notes`
- **File Tracking System**: `created_files` set prevents duplicate headers when multiple steps write to same file
- **Content Formatting**: Proper headers and separators maintained when multiple steps target the same output file
- **Directory Management**: `os.makedirs(exist_ok=True)` ensures parent directories exist for each output file

### New Syntax Examples:
```markdown
## STEP1
@output-file planning/{this-week}
Generate weekly planning based on goals.

## STEP2  
@output-file daily/{today}
Generate daily task list.

## STEP3
Generate reflection.  <!-- Uses default: journal/{this-week} -->
```

### Testing Coverage:
- **4 comprehensive integration tests** covering multi-file creation, directory nesting, same-file multiple steps, and file appending
- **3 additional auto-injection tests** verifying default parameter behavior in various scenarios
- **Full workflow execution testing** with mocked step content generation
- **Pattern resolution testing** for complex nested paths and time-based patterns

### Architecture Benefits:
- **User Discoverability**: Auto-injection provides sensible defaults without file modification
- **Clean Data Structure**: Functional defaults at configuration level maintain user file control
- **Extensible Pattern System**: Time-based patterns work consistently for both input and output files
- **Performance Optimized**: Per-step resolution avoids unnecessary file system operations

### Files Modified:
- **`core/assistant_config.py`**: Added `step_output_files` field and parameter extraction logic (lines 835-861)
- **`workflows/weekly_daily_journal/workflow.py`**: Complete refactor from single-file to per-step file resolution (lines 55-115)
- **`core/pattern_resolution.py`**: Enhanced to handle path templates with embedded patterns (lines 72-106)
- **`tests/test_flexible_output.py`**: New comprehensive test suite with 4 integration tests (260 lines)
- **`tests/test_assistant_config.py`**: Added 3 auto-injection tests for parameter behavior (90 lines)

### Test Results:
- **159 tests passing** ✅ (7 new flexible output tests added)
- **All existing functionality preserved** while adding major new capabilities
- **Complete integration testing** with real workflow execution and file creation

This implementation transforms the workflow system from journal-specific to a flexible, time-aware content generation system with clean architecture supporting unlimited workflow step customization.

---

## 2025-07-19 - Workflow Module Structure Refactor

**Reorganized workflow modules into nested structure with clearer naming for better maintainability and extensibility**

### Changes Made:
- **Created `workflows/` Directory**: All workflows now organized under a single parent directory for better structure
- **Nested Module Structure**: `weekly_daily_journal_workflow/` → `workflows/weekly_daily_journal/` for extensible organization
- **File Naming Improvement**: `agent.py` → `workflow.py` to accurately reflect the file's purpose as workflow orchestration logic
- **Updated Import System**: Modified dynamic import logic to use new nested structure: `workflows.{workflow_name}.workflow`
- **Proper Python Modules**: Added `__init__.py` files for correct module structure

### Technical Details:
- **Import Path Updates**: All imports changed from `weekly_daily_journal_workflow.agent` to `workflows.weekly_daily_journal.workflow`
- **Configuration Updates**: Updated `core/defaults.py` workflow name from `weekly_daily_journal_workflow` to `weekly_daily_journal`
- **Dynamic Loading**: Modified `main.py` to use `workflows.{config.workflow}.workflow` import pattern
- **Test Suite Updates**: Updated all test files with new import paths and module references

### Benefits Achieved:
- **Better Organization**: Future workflows can be added as `workflows/new_workflow/workflow.py`
- **Clearer Naming**: `workflow.py` clearly indicates the file contains workflow orchestration logic
- **Extensible Structure**: Nested structure supports auto-discovery of available workflows
- **Consistent Pattern**: Establishes clear pattern for future workflow development

### Files Modified:
- **New Structure**: Created `workflows/` directory and moved `weekly_daily_journal_workflow/` → `workflows/weekly_daily_journal/`
- **Renamed**: `agent.py` → `workflow.py` within the workflow module
- **Updated Imports**: `main.py`, `tests/test_agent.py`, `tests/test_scheduler_integration.py`, `tests/test_assistant_config.py`
- **Configuration**: `core/defaults.py` - Updated default workflow name
- **Module Structure**: Added `workflows/__init__.py` and `workflows/weekly_daily_journal/__init__.py`

### Test Results:
- **152 tests passing** ✅ (all workflow-related tests updated and passing)
- **3 tests failing** (pre-existing unrelated issues: AI schedule parsing and path resolution edge cases)
- **1 test skipped**

This refactor establishes a clean, extensible foundation for workflow management while maintaining full backward compatibility for existing assistant configurations.

---

## 2025-07-18 - Parameter Extraction System Implementation

**Implemented unified parameter extraction system with path-aware, non-recursive pattern resolution**

### Major Features Implemented:
- **Unified Parameter Syntax**: All parameters now use `@param-name value` format (both `@param value` and `@param: value` supported)
- **Clean Pattern Substitutions**: Patterns use `{latest}`, `{today}`, `{this-week}` without @ prefix
- **Path-Aware Resolution**: `{latest}` searches vault root, `journal/{latest}` searches only journal directory
- **Non-Recursive Directory Searching**: Pattern resolution respects directory boundaries, never searches subdirectories recursively
- **Input vs Output File Distinction**: `@input-file` resolves to multiple files for context, `@output-file` resolves to single paths for file creation

### Core Components Added:
- **`core/parameter_extraction.py`**: Generic parameter parsing system with `ExtractedParameter` and `ParameterExtractionResult` data structures
- **Updated `core/prompt_file_injection.py`**: Now uses new parameter system with `@input-file` directives
- **Enhanced `core/pattern_resolution.py`**: Made non-recursive, added default behavior for patterns without counts

### New Syntax Examples:
```markdown
@input-file goals.md
@input-file journal/{latest:3}
@output-file planning/{today}
@output-file reports/{this-week}
```

### Key Security/Correctness Improvements:
- **Non-Recursive Pattern Resolution**: `journal/{latest}` only searches `journal/` directory, never `journal/nested/` subdirectories
- **Path-Aware Pattern Context**: Each pattern resolves in its specified directory context only
- **Enhanced Pattern Behavior**: Patterns without counts (e.g., `{latest}`) now find all files up to the 50-file limit instead of just 1

### Testing Enhancements:
- **18 parameter extraction tests** covering all syntax variations and edge cases
- **12 pattern resolution tests** including 2 new non-recursive behavior tests
- **Comprehensive path-aware testing** with complex directory structures to verify non-recursive behavior
- **Self-documenting tests** that serve as regression guards against recursive directory searching

### Technical Details:
- **Backward Compatibility**: Removed @ prefix from all patterns (no backward compatibility - @ prefixes now fail as intended)
- **File Extension Handling**: System remains markdown-only by design - always adds `.md` extension for file loading, strips for display headers
- **Input vs Output Logic**: `@input-file` patterns resolve to multiple `ExtractedParameter` objects (one per file), `@output-file` patterns resolve to single paths
- **Pattern Count Defaults**: `{latest}` finds all files (up to 50), `{latest:3}` finds exactly 3 files

### Files Modified:
- `core/parameter_extraction.py` - New generic parameter parsing system (238 lines)
- `core/prompt_file_injection.py` - Updated to use new parameter system
- `core/pattern_resolution.py` - Made non-recursive, updated pattern parsing
- `tests/test_parameter_extraction.py` - New comprehensive test suite (527 lines)
- `tests/test_pattern_resolution.py` - Enhanced with non-recursive behavior tests

### Test Results:
- **30 parameter extraction tests passing** ✅ (18 new tests)
- **12 pattern resolution tests passing** ✅ (2 new non-recursive tests)
- **All existing functionality preserved** while adding new capabilities

This implementation completes the parameter extraction system refactoring plan, establishing a robust foundation for future parameter-based features with clean, consistent, and secure syntax.

---

## 2025-07-18 - Pattern Resolution Code Cleanup

**Simplified pattern resolution by removing unnecessary abstraction layers**

### Changes Made:
- **Moved Logic Inline**: Eliminated intermediate functions `_apply_time_filter()` and `_resolve_time_pattern_core()`
- **Clearer Architecture**: Made the fundamental difference between multiple vs single file resolution more obvious
- **Code Reduction**: Removed 56 lines of unnecessary abstraction while maintaining all functionality

### Technical Details:
- **`resolve_time_pattern_to_many()`**: Now contains file filtering logic inline - scans filesystem and filters existing files
- **`resolve_time_pattern_to_single()`**: Now contains date calculation logic inline - calculates dates mathematically without touching filesystem
- **Maintained Utilities**: Kept truly reusable functions like `_parse_time_pattern_with_count()`, `_get_week_start_date()`, and file filtering helpers

### Test Results:
- **134 tests passing** ✅ (all pattern resolution tests continue to pass)
- **1 test failing** (pre-existing network connectivity issue)
- **1 test skipped**

This cleanup makes the code more straightforward by removing abstraction layers that weren't actually providing reuse.

---

## 2025-07-18 - Pattern Resolution Architecture Refactor

**Extracted pattern resolution functions into reusable module with future-based patterns**

### Changes Made:
- **New Module**: Created `core/pattern_resolution.py` with pure pattern resolution functions
- **Function Extraction**: Moved all time-based pattern logic from `core/prompt_file_injection.py` to new module
- **Clear API Design**: Separate functions for single (`resolve_time_pattern_to_single`) vs multiple (`resolve_time_pattern_to_many`) file resolution
- **Future Patterns**: Added `@next-week` and `@tomorrow` patterns for forward-looking workflows
- **Updated Naming**: Changed `markdown_root` → `vault_root` throughout for consistency

### Technical Details:
- **Core Functions**: `resolve_time_pattern_to_many()` returns `List[str]` for context loading, `resolve_time_pattern_to_single()` returns `str` for output paths
- **Shared Logic**: All date parsing, week calculations, and filtering logic unified in private core functions
- **No Code Duplication**: Single source of truth for pattern resolution with different interfaces
- **Future-Ready**: New patterns enable flexible output file generation for upcoming workflow enhancements

### New Patterns Added:
- `@next-week` - Next week start date (respects assistant's week_start_day)
- `@tomorrow` - Next day date
- Enhanced pattern support in both single and multiple resolution modes

### Files Modified:
- `core/pattern_resolution.py` - New module with extracted functions
- `core/prompt_file_injection.py` - Updated to use new module, removed 223 lines of duplicated code
- `tests/test_pattern_resolution.py` - New comprehensive test suite (10 tests)

### Test Results:
- **134 tests passing** ✅ (10 new pattern resolution tests added)
- **1 test failing** (pre-existing network connectivity issue)
- **1 test skipped**

This refactor prepares the pattern system for flexible output file generation while maintaining all existing context loading functionality.

---

## 2025-07-18 - Workflow Module Rename: sequential_journal_workflow → weekly_daily_journal_workflow

**Renamed workflow module to better reflect its purpose and prepare for flexible output functionality**

### Changes Made:
- **Module Rename**: Changed `sequential_journal_workflow/` to `weekly_daily_journal_workflow/` to better describe its weekly/daily journal focus
- **Comprehensive Reference Updates**: Updated all imports, configuration references, and documentation across the codebase
- **Test Suite Updates**: Modified all test files to use new module name while maintaining full functionality

### Technical Details:
- **Directory Rename**: `mv sequential_journal_workflow weekly_daily_journal_workflow`
- **Configuration Updates**: Updated `core/defaults.py`, `config.yml`, and vault configuration files
- **Import Updates**: Modified all Python imports in test files and core modules
- **Documentation Updates**: Updated README.md, CLAUDE.md, and all vault configuration specifications

### Files Modified:
- `core/defaults.py` - Updated default workflow name
- `tests/test_agent.py` - Updated import and patch references
- `tests/test_scheduler_integration.py` - Updated all workflow references
- `tests/test_assistant_config.py` - Updated 22 workflow name references
- `config.yml` - Updated workflow configuration
- `CLAUDE.md` - Updated module documentation
- All vault configuration documentation files

### Test Results:
- **124 tests passing** ✅ (same pass rate as before rename)
- **1 test failing** (pre-existing network connectivity issue in AI schedule parsing)
- **1 test skipped**

This rename prepares the module for upcoming flexible output functionality while maintaining backward compatibility for existing assistant configurations.

---

## 2025-07-16 - Fix Logging File Organization and Tagging System

**Consolidated multiple log files into cleaner structure with searchable tag labels**

### Changes Made:
- **System Log Consolidation**: Replaced multiple system log files (scheduler.md, assistant-config.md, global.md) with single `system.md` file
- **Tag-Based Entry Labeling**: Tags now appear as searchable `[tag]` labels within log entries instead of determining filenames
- **Vault Log Organization**: Vault logs use `{assistant}.md` files within vault's logs directory for better organization
- **Improved User Onboarding**: Reduces clutter from 3 empty log files to 1 meaningful system log while maintaining searchability

### Technical Implementation:
- **LocalLogger Logic**: Modified filename determination in `core/local_logging.py` (lines 31-44)
  - System logs (`/app/data/logs` path) → always use `system.md`
  - Vault logs (custom paths) → extract assistant name from global_id format `vault/assistant`
- **Entry Format**: Log entries include `[{tag}] {emoji} {message}` for searchable labeling
- **Backward Compatibility**: Maintained test compatibility with `assistant_name` and `vault_root` properties

### Test Fix:
- Updated `test_global_logger_path` in `tests/test_unified_logging.py` to expect `system.md` filename
- Verified tag functionality works correctly for entry labeling

### Test Results:
- **123 tests passing** ✅ (resolved logging-related test failure)
- **1 test failing** (pre-existing asyncio issue unrelated to changes)
- **1 test skipped**

### Commands Used:
```bash
python run_tests.py
python -m unittest tests.test_unified_logging.TestLocalLogger.test_global_logger_path -v
```

---

## 2025-07-15 - AI-Powered Schedule Parsing with Structured Output

**Implemented intelligent natural language to cron expression conversion with comprehensive validation and testing**

### Changes Made:
- **AI Schedule Parsing**: Added `parse_schedule()` function that converts natural language schedules to valid cron expressions using Gemini AI
- **Structured Output**: Implemented `CronExpression` dataclass for robust AI response handling, eliminating parsing issues with markdown formatting
- **Comprehensive Validation**: Built robust cron expression validator supporting ranges, steps, comma-separated lists, and all standard cron formats
- **Event Loop Management**: Fixed async execution issues using `unittest.IsolatedAsyncioTestCase` for proper async test handling

### Technical Details:
- **Core Functions**: Enhanced `core/chat.py` with optional `output_type` parameter for structured AI responses
- **Validation Logic**: Added `validate_cron_expression()` and `validate_single_cron_field()` with comprehensive range and format checking
- **Error Handling**: AI-generated responses are validated before returning, ensuring only valid cron expressions are accepted
- **Environment Loading**: Moved `load_dotenv()` into `create_agent()` function for reliable API key access

### Test Coverage:
- **124 tests passing** (1 failure, 1 skipped): Complete validation including real AI integration tests
- **Mocked Unit Tests**: Test function logic with fake AI responses for fast, reliable testing
- **Integration Tests**: Test with real Gemini AI using rate limiting and proper async handling
- **Validation Tests**: Comprehensive testing of cron expression validation logic

### Real AI Results:
- **"weekdays at 9am"** → `0 9 * * 1-5` ✅
- **"daily at midnight"** → `0 0 * * *` ✅  
- **"every monday at noon"** → `0 12 * * 1` ✅
- **"first day of every month at 8am"** → `0 8 1 * *` ✅
- **"every 15 minutes"** → `*/15 * * * *` ✅

### Commands Used:
```bash
# Run all tests
python run_tests.py

# Run specific test modules  
python -m unittest tests.test_assistant_config.TestCronValidation -v
python -m unittest tests.test_assistant_config.TestScheduleParsing -v
python -m unittest tests.test_assistant_config.TestScheduleParsingIntegration -v
```

---

## 2025-07-15 - Vault-Based Assistant Configuration System

**Complete migration from namespace-based to vault-based assistant configuration architecture**

### Changes Made:
- **Vault-Based Configuration**: Replaced namespace-based system with vault-aware configuration using `AssistantConfig` dataclass
- **Comprehensive Test Coverage**: Added 75 unit tests covering all aspects of the new configuration system
- **Legacy Test Migration**: Updated existing tests in `test_agent.py` and `test_scheduler_integration.py` to use new vault-based interface
- **Configuration Discovery**: Implemented automatic vault discovery and assistant file parsing with robust error handling
- **Workflow Integration**: Updated `sequential_journal_workflow/agent.py` to use `load_workflow_content()` instead of deprecated namespace loading
- **Scheduler Integration**: Updated `main.py` scheduler setup to use new vault-based configuration manager

### Technical Details:
- **Core Module**: Enhanced `core/assistant_config.py` with vault discovery, config parsing, validation, and management
- **Configuration Format**: Assistants now use `vault/name` global IDs with file-based configuration sections
- **Data Structures**: Added `AssistantConfig`, `WorkflowContent`, and `AssistantConfigManager` classes
- **Scheduler Integration**: Jobs now use `config.scheduler_job_id` and `config.global_id` for proper identification
- **Error Handling**: Comprehensive validation with informative error messages for configuration issues
- **Directory Management**: Automatic creation of required assistant directories and default configuration files

### Test Results:
- **115 tests passing** (1 skipped): Complete system validation including integration tests
- **Removed Legacy Code**: Eliminated obsolete `test_assistant_config_old.py` that was importing deprecated functions
- **Migration Success**: All existing functionality preserved while enabling vault-based organization

### Commands Used:
```bash
# Run comprehensive test suite
python run_tests.py

# Run specific test modules
python -m unittest tests.test_assistant_config -v
python -m unittest tests.test_agent -v
python -m unittest tests.test_scheduler_integration -v
```

---

## 2025-07-12 - Pure Utility Logger Refactor and Core Directory Cleanup

**Completed transition to pure utility logging pattern throughout the codebase**

### Changes Made:
- **UnifiedLogger Refactor**: Converted from assistant-coupled design to pure utility pattern
- **New Interface**: `UnifiedLogger(tag="name", log_path="/app/data/logs")` with sensible defaults
- **Core Directory Cleanup**: Updated all core modules to use new logger interface
- **Legacy Removal**: Eliminated outdated `project_assistant` terminology and backward compatibility code
- **Function Cleanup**: Streamlined `create_agent()` to only accept needed `instructions` parameter

### Technical Details:
- **Before**: `UnifiedLogger.for_assistant(config)` and `UnifiedLogger.for_system("context")`
- **After**: `UnifiedLogger(tag="scheduler")` with default global logs or custom `log_path` for vault-specific logging
- **Core Files Updated**: `assistant_config.py`, `chat.py`, `prompt_file_injection.py`, `local_logging.py`
- **Orchestration Pattern**: Assistant-aware code constructs log paths, utilities remain pure
- **Hybrid Architecture**: Maintains performance while enabling vault-specific logging when needed

### Benefits Achieved:
- **Pure Utility Pattern**: Logger has no coupling to assistant/vault concepts
- **Clear Responsibilities**: Each module creates focused loggers with descriptive tags
- **Flexible Usage**: Can be used for any logging scenario (system, API, workflows, vault-specific)
- **Performance Optimized**: No unnecessary object overhead in utility functions
- **Architecture Consistency**: All components follow hybrid assistant-aware design pattern

All 68 tests passing. Logger now serves as true utility while maintaining all advanced features.

---

## 2025-07-12 - Hybrid Assistant-Aware Architecture Implementation

**Major architectural upgrade implementing hybrid assistant-aware design pattern**

### Changes Made:
- **Fixed Critical Broken State**: Resolved confused function signatures in `sequential_journal_workflow/agent.py` that mixed old/new patterns
- **Hybrid Architecture**: Implemented three-layer pattern with assistant-aware orchestration and parameter-based utilities
- **Clean Function Signatures**: `run_workflow(assistant_config)` now uses pure AssistantConfig objects
- **Performance Optimized**: Utility functions remain parameter-based for efficiency (`embed_files_in_prompt(prompt, vault_path)`)
- **Enhanced Week Configuration**: Added support for configurable week start days from assistant config

### Technical Details:
- **Orchestration Layer**: `run_workflow()` receives full `AssistantConfig` and extracts needed parameters
- **Implementation Layer**: `run_step()` receives specific parameters for focused functionality
- **Utility Layer**: File processing functions remain lightweight and efficient
- **Scheduler Integration**: Updated `main.py` to pass complete config objects: `args=[config]`
- **Assistant-Aware Logging**: Maintained throughout workflow orchestration layer

### Benefits Achieved:
- **Clear Architectural Boundaries**: Separation between assistant orchestration and utility functions
- **Future Extensibility**: New assistant config fields automatically available at orchestration level
- **Performance Maintained**: No unnecessary object overhead for utility functions
- **Testing Simplified**: Focused test strategies per architectural layer

All 68 tests passing. System restored to full functionality with improved architecture.

---

## 2025-07-11 - Completed Unified Logging Replacement

**Successfully replaced all logfire and project_logger calls throughout the codebase**

### Files Updated:
- **core/assistant_config.py**: Replaced all logfire and project_logger calls with unified logger, added vault-aware logging for configuration operations
- **weekly_daily_journal_workflow/agent.py**: Implemented vault-aware logging for workflow operations, maintaining rich context for step tracking
- **core/prompt_file_injection.py**: Updated all logging calls and function signatures to support logger parameter injection throughout file processing chain
- **core/chat.py**: Replaced logfire error logging in chat completion functions with unified logger
- **tests/test_unified_logging.py**: Fixed test isolation by properly mocking environment variables

### Results:
- **68 tests passing**: All unit tests confirm unified logging system works correctly
- **Zero breaking changes**: Backward compatibility maintained through global logger instance
- **Complete transition**: All active logfire/project_logger calls replaced, only legitimate uses remain in logging system itself
- **Vault Isolation**: Each vault gets separate log files for better user experience managing multiple vaults

### Commands Used:
```bash
# Test unified logger functionality
python test_unified_logger.py
python -m unittest tests.test_unified_logging -v
python run_tests.py

# Verify logfire integration
ENABLE_LOGFIRE=true python -c "from core.logging import logger; logger.setup_instrumentation()"
```

---

## 2025-07-11 - Unified Logging System Overhaul

**Implemented centralized logging wrapper with vault awareness and configurable backends**

### Changes Made:
- **Core Logging Module**: Created `core/logging.py` with `UnifiedLogger` class for centralized logging interface
- **Vault-Aware Local Logging**: Enhanced `core/local_logging.py` to support vault-specific log directories (`{vault_root}/logs/`)
- **Configurable Logfire Integration**: Added `ENABLE_LOGFIRE` environment variable (default: false) for optional observability
- **Automatic Instrumentation**: Integrated FastAPI and PydanticAI instrumentation setup when logfire enabled
- **Main.py Integration**: Replaced all logfire calls with unified logger, maintaining structured logging context
- **Test Coverage**: Added 14 comprehensive unit tests for all logging functionality
- **Test Compatibility**: Updated scheduler integration tests to mock new unified logger

### Technical Details:
- **Flexible Backend Management**: Easy to swap logfire for other platforms (Sentry, DataDog) or add traditional Python logging fallback
- **Per-Call Local Logging**: Use `local_logging=True` parameter for user-facing workflow status (sparing use)
- **Structured Context**: Rich kwargs passed to logfire for debugging, fallback to Python logging when disabled
- **Global Logger Instance**: `logger` and `project_logger` compatibility aliases maintain existing interfaces

---

## 2025-07-10 - Docker Timezone Configuration

**Added proper timezone support for container scheduling**

### Changes Made:
- **Dockerfile Enhancement**: Added `tzdata` package for comprehensive timezone support
- **Docker Compose Configuration**: Added `TZ` environment variable for user timezone setting
- **Documentation**: Updated setup instructions with timezone configuration step

### Technical Details:
- **Robust Timezone Handling**: Installed `tzdata` package in Dockerfile for full timezone database
- **Simple Configuration**: Users only need to set `TZ=America/Vancouver` in docker-compose.yml
- **Automatic Detection**: Container respects the TZ environment variable for all scheduling operations

---

## 2025-07-10 - Vault Configuration Refactor (vault_path → vault_root)

**Simplified vault configuration for better user experience**

### Changes Made:
- **User-Friendly Configuration**: Changed `vault_path` to `vault_root` in assistant configuration
- **Relative Path Approach**: Users now specify directory names instead of full container paths
- **Simplified Setup**: Users only need to know their vault names, not internal container paths
- **Backward Compatibility**: Removed by user request to reduce complexity

### Technical Details:
- **Configuration Field**: Renamed `vault_path` to `vault_root` in `AssistantConfig` dataclass
- **Path Construction**: Added `vault_path` property that constructs full paths internally from `vault_root`
- **Container Root**: Added `CONTAINER_DATA_ROOT = '/app/data'` constant for path construction
- **Validation**: Updated validation to ensure `vault_root` is relative (no leading slash)

All 54 tests passing. No changes needed to existing vault data or docker-compose setup.

---

## 2025-07-10 - Namespace Loading Architecture Refactor

**Major architectural refactor to improve performance and code maintainability**

### Changes Made:
- **Performance Optimization**: Reduced file I/O operations from 3-4 reads per workflow to 1 read per workflow
- **Single File Loading**: Replaced multiple independent namespace loading functions with unified `load_namespace_file()` function
- **Auto-Generation**: System now creates missing namespace files from defaults instead of silent fallbacks
- **Code Reduction**: Net reduction of 156 lines of code while maintaining all functionality
- **Structured Data**: Added `NamespaceContent` dataclass for organized namespace data handling

### Technical Details:
- **Removed Legacy Functions**: Eliminated `discover_workflow_steps_from_namespace()`, `load_prompt_from_namespace()`, and `load_assistant_system_instructions_from_namespace()`
- **Unified Loading**: Created single `load_namespace_file()` function in `core/assistant_config.py`
- **Dynamic Agent Instructions**: Made LLM instructions loadable from markdown files using `ASSISTANT_SYSTEM_INSTRUCTIONS` section
- **Simplified Workflow**: Streamlined `weekly_daily_journal_workflow/agent.py` to use single namespace loading approach

All 54 tests passing. System maintains full functionality while operating more efficiently.
