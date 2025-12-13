# Summary of “I Read Everything: Google, Anthropic, Manus on Long‑Running Agents”

The article synthesizes recent work from Google, Anthropic, Stanford/SambaNova (ACE), and Manus on how to make **long‑running AI agents** actually work in practice. The central topic is **in‑session context engineering**—how you manage what an agent *sees* and *remembers* during a single long task.

## Core Problem: Context Rot in Long Sessions

- Early in a task, agents reason well. After 20–30 minutes or dozens of tool calls, they:
  - Repeat themselves  
  - Forget earlier constraints  
  - Re‑try failed approaches  
- This isn’t about cross‑session memory (domain memory); it’s what happens *within* one run.
- The key insight: **bigger context windows don’t fix this; they often make it worse**.
  - Every token competes for attention.
  - Dumping 100k tokens of history into the prompt makes important details harder to find.
  - Agents “forget” not because they lack space, but because **signal is drowned in noise**.

The naive approach—**accumulation** (“just append all history into the context”)—fails at scale.

## Context as a Compiled View (Not a Log Dump)

The new pattern from Google, Anthropic, Manus, and ACE:

- Treat the context at each step as a **compiled, curated view** of what matters *right now*, not a raw running log.
- Instead of stuffing everything in, the system:
  - **Clears the desk** each step
  - **Selects or synthesizes** only the information relevant to the current subtask
- Google’s Agent Development Kit (ADK):
  - Actively recomputes what to show the model at each step.
- ACE (Stanford + SambaNova):
  - Shows agents can **notice and correct their own mid‑task mistakes**, updating which information they include going forward.
- Manus:
  - Shares “battle‑tested” lessons from multiple redesigns to keep their popular consumer agent focused even when juggling many tools.

## The Four-Layer Memory Model

The article organizes memory for agents into four layers:

1. **Working Context**
   - What the model sees on *this* step (instructions, key facts, recent moves).
   - Must be **small, relevant, and carefully curated**.

2. **Session State**
   - The ongoing state of this single task/run: decisions made, active subtasks, constraints.
   - Feeds into the working context but is not all shown at once.

3. **Memory**
   - More persistent knowledge that spans tasks or sessions.
   - Structured external records the agent can retrieve from (e.g., knowledge bases, project memory).

4. **Artifacts**
   - The durable outputs: docs, code, plans, logs, reports.
   - These become the “library” for future work.

**Why separation matters:** Without clear layers, everything collapses into one giant, noisy history; with layers, you can systematically decide what to show versus what to store.

## Nine Scaling Principles (High-Level)

From the papers and Manus’s redesigns, the article extracts patterns that make long‑running agents stable and scalable, including:

- **Curated working set, not full history** (compiled view per step)
- **Structured summaries** instead of raw transcripts
- **Explicit attention budgets** (justify each token you include)
- **Tool‑aware context** (only show tools the info they actually need)
- **Reflections and self‑correction** mid‑task (ACE style)
- **Externalized domain memory** (don’t overload the session with long‑term facts)
- **Clear interfaces between agents** when using multi‑agent setups
- **Caching and reuse** of expensive computations/views
- **Observability/tracing** so you can debug what the agent saw and why it failed

## Nine Failure Modes

When teams ignore those principles, they see recurring problems:

- Agents that **lose the thread** mid‑task.
- Contexts that **grow unbounded**, exploding cost and latency.
- Important constraints **disappearing** under mountains of irrelevant tokens.
- Multi-agent systems that **add noise and confusion** rather than clarity.
- Summaries that are **too lossy**, dropping key details.
- Memories that are **never retrieved**, making “memory systems” useless in practice.
- Systems that are **impossible to debug** because you can’t reconstruct what the model actually saw.
- Architectures that **cap model capability** regardless of how smart the underlying LLM is.

## What Becomes Possible with Good Context Engineering

With correct architecture, agents can:

- **Run for hours instead of minutes** without degradation.
- Tackle **multi-step, tool-heavy workflows** reliably.
- **Learn within a session**, adjusting strategy as they go.
- Produce and update **artifacts and strategies** that improve future runs.
- Deliver **qualitatively new capabilities** rather than incremental accuracy bumps.

The article argues that the limiting factor is increasingly **memory and context architecture**, not raw model intelligence.

## 12 Design Prompts to Build Your Own System

The piece ends with 12 prompts you can use to design or audit your own agent architecture, such as:

- **State Persistence Analysis** – Decide what must be remembered vs. safely discarded.
- **View Compilation Design** – Define minimal context per decision step.
- **Retrieval Trigger Design** – Ensure stored memory actually gets used.
- **Attention Budget Allocation** – Treat prompt space like a scarce resource.
- **Summarization Schema Design** – Specify what must survive compression.
- **External Memory Architecture** – Decide what lives in storage vs. context.
- **Multi-Agent Scope Design** – Check if extra agents add clarity or just complexity.
- **Cache Stability Optimization** – Manage cost/latency at scale.
- **Failure Reflection System** – Design how agents learn from errors.
- **Architecture Ceiling Test** – Find where your harness, not the model, is the bottleneck.
- **Context Observability Audit** – Make the agent’s “view” transparent and traceable.
- **Non‑Technical Prompt** – A framing so non‑engineers can understand and participate.

---

## Practical Implementation Notes for Your App

Below is a minimal, implementation-focused way to turn the article's ideas into experiments in an app.

### 1. Start with a Simple 4-Layer Structure

Even a rough separation of concerns helps:

1. **Working Context (per step)**
   - What you actually send in the prompt.
   - Include:
     - Task instructions
     - A compact "current plan / subtask"
     - The most recent few actions + results
     - Any constraints that must never be violated

2. **Session State (in memory, not fully in prompt)**
   - A structured object for the running task, e.g.:

     ```json
     {
       "task_id": "123",
       "goals": ["Summarize docs", "Draft email"],
       "constraints": ["No external web calls", "Use Markdown"],
       "subtasks": [
         {"id": 1, "desc": "Read docs", "status": "done"},
         {"id": 2, "desc": "Draft email", "status": "in_progress"}
       ],
       "important_decisions": [
         "Chose doc A as primary source"
       ]
     }
     ```

   - You don’t dump this whole thing into the prompt; you derive the working context from it.

3. **Memory (external, across sessions)**
   - Database / vector store / key-value store.
   - Store:
     - Domain facts
     - Reusable patterns
     - Past task summaries

4. **Artifacts**
   - Files, docs, code, final outputs.
   - Link them into memory with IDs so the agent can re-open them.

### 2. Replace "Append All History" with a Compiled View

If you’re currently doing something like:

```pseudo
prompt = system + full_conversation_history + latest_user_message
```

use this pattern instead:

```pseudo
function build_prompt(session_state, history, latest_input):
    instructions = BASE_SYSTEM_PROMPT

    constraints = summarize_constraints(session_state)
    plan_snippet = summarize_current_plan(session_state)

    recent_turns = last_n_turns(history, n=3)

    reflections = last_n_reflections(session_state, n=3)

    return render_template(
      instructions=instructions,
      constraints=constraints,
      plan=plan_snippet,
      recent_turns=recent_turns,
      reflections=reflections,
      latest_input=latest_input
    )
```

Key rules:

- Limit raw history to just the last few turns.
- Carry important older info via a short **constraints** block and **plan / decisions** block.

### 3. Add Lightweight "Reflections"

After every few steps (or after a tool failure), ask the model:

```text
You are maintaining a brief running playbook for this task.

1. What did you just try?
2. What went wrong or right?
3. What should you do differently in the next steps?

Respond in this JSON format:
{
  "observation": "",
  "mistake_or_success": "",
  "adjustment": ""
}
```

- Store this JSON in `session_state.reflections`.
- When building the next prompt, include the last 1–3 reflections, not all of them.

### 4. Enforce an Attention Budget

Treat prompt space as scarce:

- Decide a max token target (e.g. 4k out of 8k).
- Before each request, estimate token lengths and, if needed:
  - Truncate history first
  - Then trim reflections
  - Then compress plan/constraints (via summarization)

Drop sections by priority when space is tight, for example:

1. System instructions, safety constraints
2. Task goals, hard constraints
3. Current subtask / plan
4. Latest user input & last few tool results
5. Reflections
6. Older history

### 5. Minimum Observability for Debugging

Log a simple trace per step:

```json
{
  "step": 12,
  "prompt_sections": {
    "instructions_tokens": 200,
    "constraints_tokens": 100,
    "plan_tokens": 150,
    "recent_turns_tokens": 300,
    "reflections_tokens": 120
  },
  "retrieved_memory_ids": ["doc_42", "pattern_7"]
}
```

This lets you see:

- Whether a "forgotten" fact was present in the prompt.
- Whether you should adjust compilation rules instead of blaming the model.

### 6. Simple First Experiment Plan

1. Record your current append-all behavior as a baseline.
2. Implement a `session_state` object and `build_prompt()` that:
   - Uses only the last 3–5 turns.
   - Adds `constraints` and `plan` blocks derived from state.
3. Add a reflection call every N steps and include the last 2–3 reflections per prompt.
4. Compare:
   - Repetition frequency.
   - Constraint adherence after 20–30 minutes.
   - Token/cost savings.

---

## Rough Sketch: Shared Context Compiler for Chat + Workflows

Goal: keep existing primitives (markdown logs, stateless step engine) but add an opt-in “context compiler” that curates a working view for long runs.

Core idea:
- One compiler component that assembles instructions/constraints, a restated plan, last N turns, last M reflections, and recent tool outputs under a token budget with drop-order rules.
- Stores compact state per session/run (small cache in `system/`), but continues writing full chat/workflow artifacts to markdown for user transparency.

Chat (new “Endless” mode):
- Mode toggle uses the compiler each turn instead of full history.
- Markdown transcript remains the user-facing record; compiler state is internal and can be rebuilt by replaying markdown if needed.
- Observability: per-turn trace of what sections were included/dropped.

Workflows (new directive):
- Add an opt-in directive (e.g., `@context-helper on`, with knobs like `recent_turns`, `reflections`, `budget`).
- Before a step runs, the compiler materializes a curated snippet (written to a helper file or injected as preamble). If it fails, the step runs normally.
- Keeps the step engine intact; no reordering or new goals—just resurfacing constraints/recents to reduce boilerplate.

Boundaries and safety:
- Helper is not a planner: it never invents steps or goals, only compiles existing signals.
- Precedence: user instructions/directives > workflow structure > helper context; on conflict, drop helper content and log.
- Fail-open: if the compiler errors or exceeds budget, skip injection and continue.

Why this path:
- Centralizes token budgeting, reflections, and drop-order logic once, instead of copy/pasting “state.md” patterns into every workflow.
- Preserves markdown-first UX while enabling long-running chat and tool-heavy workflows to stay coherent with a curated working context.
