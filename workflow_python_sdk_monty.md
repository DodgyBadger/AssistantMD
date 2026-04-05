# Monty Sandbox: Unified Authoring Surface Briefing

## Status
Exploratory — emerged from design discussion on the Python SDK workflow engine direction.

## Context
The `feature/workflow_python_sdk` branch has been building a constrained Python SDK (`Step`, `Workflow`, `File`, `Var`) as a second authoring mode alongside the existing string DSL. That work is well advanced (Phases 1–4 substantially complete, shared runtime extraction in place).

During design discussion of the next primitive evolution (`Generate` + `Write`/`Output` split, `Context()` as a sink for unifying workflows and context templates), a fundamentally different approach surfaced: replace the constrained SDK with a full Python sandbox using **Pydantic Monty**.

## What Is Monty
- A minimal Python interpreter written in Rust by the Pydantic team.
- Not CPython with restrictions. Not WASM. A from-scratch bytecode VM using Ruff's parser.
- The sandbox is airtight **by construction**: no filesystem, no network, no imports, no OS access. These capabilities don't exist in the runtime — they aren't blocked, they're absent.
- The only way sandboxed code can interact with the outside world is through **external functions you explicitly register** on the host side.
- Supports: functions, closures, comprehensions, f-strings, async, dataclasses (returned from host).
- Does not yet support: class definitions (coming soon), match statements, full stdlib. `re`, `datetime`, `json` coming soon.
- Microsecond startup (~4.5μs without type checking). ~5MB package. Runs in-process.
- `pip install pydantic-monty`

Source: https://pydantic.dev/articles/pydantic-monty / https://github.com/pydantic/monty

## How It Maps To AssistantMD

### Execution Model
```
┌─────────────────────────────────┐
│  Monty sandbox                  │
│                                 │
│  User's workflow/template code  │
│  (real Python — loops, ifs,     │
│   f-strings, functions, etc.)   │
│                                 │
│  Can ONLY call registered       │
│  external functions.            │
└──────────┬──────────────────────┘
           │ calls
           ▼
┌─────────────────────────────────┐
│  Host (AssistantMD server)      │
│                                 │
│  Registered external functions: │
│  - read_files() → vault access  │
│  - write_file() → vault writes  │
│  - llm_generate() → LLM calls  │
│  - write_context() → chat ctx   │
│  - import_urls() → import pipe  │
│  - read_var() / write_var()     │
│  - date/path helpers            │
│                                 │
│  Scoped by frontmatter config.  │
└─────────────────────────────────┘
```

Code inside Monty sees only function signatures and docstrings. When execution hits a registered function call, Monty pauses, calls back into real Python on the host, gets the result, and returns it to the sandbox.

### What This Replaces
The constrained SDK primitive design (`Generate`, `Output`, `File`, `Var`, `Context`, `Branch`, `ForEach`) collapses into a single question: **what external functions do we register?**

| Constrained SDK approach | Monty approach |
|---|---|
| Custom `Generate`, `Output` primitives | `llm_generate()`, `write_file()` external functions |
| AST allowlist enforcement | Monty runtime — only registered functions exist |
| No f-strings, no loops, no conditionals | Full Python |
| SDK surface to document and maintain | Function signatures are the documentation |
| Flow primitives (`Branch`, `ForEach`) | Native `if`/`for` |
| Separate `Context()` sink primitive | `write_context()` external function |

### Frontmatter Remains The Security Boundary
The YAML frontmatter declares:
- Which vault paths are accessible (read/write)
- Which model to bind
- Which tools are available
- Schedule / context template mode

The host-side implementation of each registered function enforces these scopes. The sandbox code can *ask* for things but only through the provided functions, and those functions reject anything outside the declared scope.

## Unified Authoring Surface

### The Core Insight
Workflows and context templates are structurally the same thing. They differ only in where the output goes (vault files vs. chat agent context). With Monty, both become: markdown file + frontmatter config + Python code block calling registered functions.

A single authoring surface covers three concerns from one markdown file:
1. **Context** — what the agent knows (files loaded, instructions injected)
2. **Logic** — how data flows and transforms (filtering, conditionals, formatting)
3. **Capabilities** — what the agent can do (custom tools defined in template code)

### Custom Tools
A template author can define custom tool logic that the chat agent can call during a session. The logic runs in Monty (safe), backed by registered external functions (scoped). This means:

| Today | With Monty |
|-------|-----------|
| Fixed tool set | Fixed tools + template-defined tools |
| Context templates only shape the system prompt | Templates can also shape available capabilities |
| Workflow logic limited to step sequencing | Arbitrary Python orchestration |
| New tool behavior requires app code changes | Tool behavior authorable in markdown files |

### Import As An External Function
Direct web extraction in workflows routes through `import_urls()` — content lands in vault files via the existing import pipeline, not raw into prompts. If direct web extraction is needed, it goes through an LLM step with tool access (which already carries untrusted-content markers). No separate `Fetch` primitive needed.

## Relationship To Current Work

### What Carries Forward
- Shared runtime services extracted under `core/workflow/` (input resolution, output resolution, tool binding, execution prep) — these become the implementation behind registered external functions.
- Frontmatter-based configuration and scoping model.
- The markdown file as canonical artifact.
- The existing string DSL continues to work unchanged.

### What Changes
- The constrained SDK primitive design (`Step`, `Workflow`, `Generate`, `Output`, etc.) may not be needed if Monty proves out. Standard Python replaces custom primitives.
- AST validation and SDK introspection tooling become less relevant — the sandbox is the security boundary, not the language surface.
- The authoring loop simplifies: LLMs write standard Python, not a custom SDK. Validation is "does it run in the sandbox" rather than "does it pass our AST allowlist."

### What Needs Investigation
1. **Monty maturity.** It's early. No class support yet. Limited stdlib. Security track record is young.
2. **Performance under real workflow loads.** Microsecond startup is promising, but LLM call latency will dominate anyway.
3. **External function design.** The registered function set *is* the API. Getting this right matters — it needs to be expressive enough for real workflows while keeping the security scope tight.
4. **Interaction with PydanticAI.** Monty's `CodeExecutionToolset` could be a natural bridge if we move toward PydanticAI integration.
5. **Migration path.** The current `python_steps` work is well advanced. Need to decide: continue the constrained SDK to stability, then evaluate Monty? Or pivot now?

## Precedent Alignment
From the earlier precedent survey:
- **Terraform's lesson** (constrained language pressure to add expressiveness) — Monty sidesteps this entirely by giving full Python.
- **Temporal's model** (orchestration vs side effects) — maps to Monty code vs registered external functions.
- **Dagster/Flyte** (declarative graph with typed wiring) — less relevant if authors write imperative Python, but the frontmatter scoping preserves the declaration-of-resources concept.
- **LangGraph** (arbitrary Python nodes) — Monty achieves the same flexibility without the security risk because the runtime is isolated.

## Open Questions
1. Should the constrained SDK (`python_steps`) remain as a simpler/safer tier alongside Monty, or does Monty fully replace it?
2. What is the minimum registered function set for a useful v1?
3. How do custom template-defined tools surface to the chat agent's tool selection?
4. Should Monty code blocks coexist with plain markdown instructions in the same file (like today's context templates), or should the file be purely code + frontmatter?
5. What does the generate → validate → repair loop look like when the code is full Python in a sandbox vs. constrained SDK calls?

## Next Step
Sketch the unified template format: frontmatter config + Monty code block + the minimum registered function set needed to cover current workflow and context template use cases.


## Additional Context: PydanticAI Integration

AssistantMD already uses PydanticAI as its agent framework. This materially changes the integration calculus for Monty:

- **Monty is built by the same team** and designed to work with PydanticAI directly.
- PydanticAI's `CodeExecutionToolset` (landing soon per their PR #4153) wraps existing PydanticAI tools so the LLM can call them from Monty code instead of via sequential tool-calling rounds.
- This means existing AssistantMD tool definitions (web search, file ops, browser, extract, workflow runner) could potentially be exposed to Monty with minimal wrapping — not a ground-up rebuild of the external function layer.
- The "CodeMode" pattern (LLM writes code instead of making sequential tool calls) could improve both latency and token efficiency for multi-step operations. Pydantic's benchmarks show fewer LLM round-trips and lower cost for equivalent tasks.
- Monty's snapshot/resume capability (serialize execution state to bytes mid-flight) could support pause/resume patterns for workflows awaiting human approval or long-running imports.

### Implication For The Registered Function Set
Rather than designing a bespoke set of external functions (`read_files`, `write_file`, `llm_generate`, etc.), the more natural path may be:
1. Expose existing PydanticAI tools to Monty via `CodeExecutionToolset`.
2. Add a thin set of workflow-specific external functions for vault I/O scoping and context injection.
3. Let the frontmatter declare which tools are available, as it does today.

This keeps the external function surface aligned with the existing tool definitions rather than creating a parallel API.
