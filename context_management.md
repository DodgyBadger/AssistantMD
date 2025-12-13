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

