# AssistantMD Python Task Blocks Sketch

## Purpose

This document sketches a new experimental authoring mode for AssistantMD workflows and related automation artifacts.

The goal is not to replace the current markdown DSL immediately.

The goal is to add a second mode that is:

- still markdown-native
- easier for LLMs to generate
- easier to validate and repair automatically
- more expressive for composition and orchestration

This mode should live alongside the current DSL for now.

## Starting Assumptions

AssistantMD should preserve its core identity:

- markdown-native and Obsidian-friendly
- focused on research and knowledge workflows
- transparent and auditable
- conservative about security and prompt injection risk

Those constraints rule out turning AssistantMD into a generic script runner or a thin wrapper over a general-purpose agent framework.

## Problem With the Current DSL

The current step-based markdown DSL has real strengths:

- it is highly local
- prompts, inputs, outputs, and intent live together
- humans can usually decipher it quickly
- it is easy to inspect directly in the vault

But it has one structural weakness that is becoming more important:

- it is a custom language

That means LLM generation depends on:

- remembering custom syntax
- remembering custom semantics
- learning engine-specific behavior
- relying on prose usage documentation that can drift

This makes fully automated workflow generation and repair harder than it should be.

## Lateral Shift, Not Capability Reduction

This proposal is intentionally a lateral move in authoring surface, not a redesign that throws away the semantic power of the current DSL.

AssistantMD already has a strong set of workflow primitives. That is not the problem.

The problem is that those primitives currently live behind a custom executable syntax that is harder for LLMs to generate and repair reliably.

The intended shift is:

- preserve the current primitives
- preserve the current flexibility
- preserve the local grouping of behavior in markdown
- move the representation of those primitives into a constrained Python SDK

In other words, the goal is not:

- fewer primitives
- less routing flexibility
- less buffer behavior
- less expressive IO

The goal is:

- the same ideas, expressed in a Python-native authoring surface

Concretely, the new mode should aim to preserve concepts equivalent to:

- file inputs
- variable and buffer outputs
- output routing
- write modes
- model selection
- tool binding
- prompt-local task definitions
- structured passing of intermediate results
- named reusable execution blocks

The runtime can still compile these Python SDK calls into the same underlying execution concepts AssistantMD already relies on.

So the innovation here is primarily:

- representation
- validation
- inspectability for the LLM
- repairability

not a reduction in workflow capability.

## Core Idea

Keep markdown as the storage and authoring medium, but let executable task definitions be written as Python SDK code blocks instead of custom directives.

In other words:

- keep the markdown file
- keep locality and inspectability
- replace the custom executable grammar with a constrained Python SDK

This is not "arbitrary Python workflows."

It is:

- Python syntax
- a narrow AssistantMD task SDK
- sandboxed execution
- compile and validation pipeline

This should be understood as re-hosting the existing DSL's core primitives inside a Python SDK, not replacing them with a smaller or less expressive model.

## High-Level Model

AssistantMD would support two authoring modes side by side.

### Mode 1: Current DSL

The existing markdown workflow system remains supported.

Use it when:

- the workflow is simple and sequential
- the current directive model is sufficient
- the user prefers the most human-readable form

### Mode 2: Python Task Blocks

Markdown files contain Python code blocks that define tasks using a constrained SDK.

Use it when:

- the workflow needs composition beyond presentation order
- an LLM is generating or repairing the workflow
- the workflow benefits from stronger validation and runtime testing
- task reuse and named composition matter

This is an additive model, not a flag day rewrite.

## Why Python Code Blocks

This direction keeps AssistantMD markdown-native while addressing the hardest problem in the current system: LLM authoring.

LLMs already know how to work with:

- Python function calls
- named arguments
- objects and classes
- docstrings
- type hints
- stack traces and real runtime errors

They do not naturally know:

- AssistantMD's custom directive syntax
- AssistantMD's implicit step semantics
- the exact rules of each workflow engine

So the idea is not to remove all DSL behavior.

It is to move the executable surface into a host language that models are already trained to use.

Put differently:

- keep the behavior model
- change the authoring representation

## Canonical Artifact

The canonical artifact remains a markdown file in the vault.

Example:

```text
<Vault>/
  AssistantMD/
    Workflows/
      Weekly Research Digest.md
      Inbox/
        Triage Imports.md
```

The file still lives comfortably in Obsidian and still acts like a readable note.

## Suggested File Shape

Example:

```markdown
---
enabled: true
schedule: "cron: 0 7 * * *"
workflow_engine: python_tasks
description: Build a daily research digest from imported notes.
---

## Notes

This workflow classifies imported research notes and writes a concise daily digest.

## Task: classify_relevance

```python
task(
    name="classify_relevance",
    model="gpt-mini",
    inputs=[
        files("Imported/Research/**/*.md", limit=25),
    ],
    output=var("relevant_notes"),
    prompt="""
    Review each note and determine relevance.
    Return structured results with:
    - path
    - relevant
    - importance
    - reason
    """,
    capabilities=["structured_extraction"],
)
```

## Task: synthesize_digest

```python
task(
    name="synthesize_digest",
    model="gpt",
    inputs=[var("relevant_notes")],
    output=file("Research/Digests/{today}", mode="overwrite"),
    prompt="""
    Write a concise markdown digest of the relevant notes.
    Include note paths and emphasize novelty.
    """,
)
```

## Task: run_digest

```python
task(
    name="run_digest",
    run=[
        run_task("classify_relevance"),
        branch(
            on=var("relevant_notes"),
            if_empty=write(
                file("Research/Digests/{today}", mode="overwrite"),
                "No high-signal new research notes today.",
            ),
            otherwise=run_task("synthesize_digest"),
        ),
    ],
)
```
```

This preserves the key property of the current DSL:

- each unit remains local
- inputs, outputs, prompt, model, and behavior live together

## Steps Become Tasks

The shift from `step` to `task` matters.

Tasks are still readable blocks in markdown, but they are no longer limited to presentation-order execution.

Tasks become:

- named
- addressable
- composable
- reusable inside the same file

This lets AssistantMD evolve from a sequential template engine toward a lightweight task composition system without abandoning the current mental model.

## Declarative First, Not Raw Scripting

The default shape should stay declarative.

A task block should mostly describe:

- model
- inputs
- outputs
- prompt
- capabilities
- structured composition primitives

That keeps tasks auditable and compact.

The system should prefer:

- `task(...)`
- `files(...)`
- `file(...)`
- `var(...)`
- `run_task(...)`
- `branch(...)`
- `foreach(...)`
- `write(...)`

over arbitrary user-authored imperative Python.

If an escape hatch is ever needed later, it should be explicitly bounded and not the default.

## Relationship to Capabilities

Conceptually, each task bundles things similar to a capability or agent spec:

- instructions
- models
- inputs
- outputs
- capabilities
- composition behavior

But AssistantMD should not expose this as abstract framework machinery first.

It should expose it as markdown-native knowledge-work building blocks.

In practice, a task is the user-facing unit.
Under the hood, the runtime can compile tasks into structured task objects and execution graphs.

This is also why the Python SDK should mirror the existing DSL's real strengths rather than inventing a new abstraction vocabulary from scratch.

If AssistantMD already has powerful ideas around routing, buffers, outputs, model binding, and tool usage, the SDK should surface those same ideas in Python form.

## Why This Helps LLM Generation

This model improves automated generation in several ways.

### 1. The SDK Is the Real Contract

Instead of relying on a long prose document explaining a custom DSL, the system can expose the actual Python SDK surface.

That means the source of truth becomes:

- function signatures
- class signatures
- docstrings
- type hints
- bundled examples

This is much less brittle than maintaining a parallel usage guide for a bespoke syntax.

### 2. The LLM Can Inspect the SDK Directly

AssistantMD can expose a purpose-built SDK inspection tool that lets the LLM discover:

- available task primitives
- argument names
- expected value shapes
- docstrings and examples

That makes the SDK effectively self-documenting.

### 3. Validation Errors Become More Legible

When generation fails, the errors look more like normal Python and schema validation errors:

- unknown keyword
- missing argument
- invalid task reference
- wrong type
- unsupported capability

Those are much easier for a model to repair than failures in a bespoke parser with opaque semantics.

## Proposed SDK Inspection Tool

AssistantMD could expose a narrowly scoped tool that inspects only the task SDK surface.

For example, it could support:

- list available task functions
- show signature for a named function
- show class definitions and docstrings
- show built-in examples

This should be intentionally narrower than arbitrary codebase exploration.

The point is not to let the model inspect everything.
The point is to let it inspect the exact authoring surface it is expected to use.

That authoring surface should correspond closely to the primitives AssistantMD already supports today, just expressed as Python functions, classes, and typed objects instead of custom markdown directives.

## Sandboxed Generate-Validate-Repair Loop

This is the other major advantage of the Python-block model.

Once the workflow authoring surface is Python-based, AssistantMD can support a much tighter repair loop:

1. generate task blocks
2. parse markdown and extract Python blocks
3. validate syntax
4. compile blocks into task objects
5. check semantic references and capability limits
6. run in a sandbox or dry-run harness
7. feed real errors back to the LLM for repair

This is much more robust than trying to repair a custom DSL using only prose instructions.

## Validation Layers

The system could validate in stages.

### 1. Markdown Structure Validation

- are there valid task sections
- are required code fences present

### 2. Python Syntax Validation

- does the code block parse

### 3. SDK Validation

- does the code construct valid `task`, `files`, `branch`, and related objects

### 4. Semantic Validation

- do referenced task names exist
- are outputs and variables used correctly
- are capabilities allowed
- are file bindings valid

### 5. Sandbox Execution

- does the task graph execute correctly in a controlled environment
- do dry runs surface runtime logic issues

## Security Model

This should not be unrestricted Python.

The runtime should treat these blocks as constrained programs.

Key boundaries:

- only approved SDK primitives available
- no arbitrary imports
- no arbitrary filesystem access
- no broad network access
- only explicit local capabilities
- resource and execution limits

This preserves AssistantMD's conservative security posture and keeps the system focused on trusted local knowledge workflows.

## Human Readability Tradeoff

This model is not automatically simpler for humans than the current DSL.

That is why coexistence matters.

The goal is not to make every workflow use this format.

The goal is to provide a second format that trades some plain-language readability for:

- stronger LLM generation
- better validation
- better composition
- better repairability

The current DSL still has an advantage for very simple sequential workflows.

## Example: Dynamic Research Workflow

This example shows why the new mode exists.

```markdown
## Task: classify_relevance

```python
task(
    name="classify_relevance",
    model="gpt-mini",
    inputs=[files("Imported/Research/**/*.md", limit=25)],
    output=var("relevance_results"),
    prompt="""
    Review each note and return structured results with:
    - path
    - relevant
    - importance
    - reason
    """,
    capabilities=["structured_extraction"],
)
```

## Task: collect_relevant

```python
task(
    name="collect_relevant",
    run=[
        foreach(
            items=var("relevance_results"),
            as_="result",
            do=when(
                expr="result.relevant == 'yes'",
                then=append_var("relevant_notes", from_field("result.path")),
            ),
        ),
    ],
)
```

## Task: write_digest

```python
task(
    name="write_digest",
    model="gpt",
    inputs=[var("relevant_notes")],
    output=file("Research/Digests/{today}", mode="overwrite"),
    prompt="""
    Write a markdown digest of the relevant notes.
    Group related findings and include note paths.
    """,
)
```

## Task: run_digest

```python
task(
    name="run_digest",
    run=[
        run_task("classify_relevance"),
        run_task("collect_relevant"),
        branch(
            on=var("relevant_notes"),
            if_empty=write(
                file("Research/Digests/{today}", mode="overwrite"),
                "No high-signal new research notes today.",
            ),
            otherwise=run_task("write_digest"),
        ),
    ],
)
```
```

This is the kind of workflow that is awkward in the current sequential DSL and a much better fit for named composable tasks.

## Skills as the Composition Layer Above Tasks

Skills still matter in this model.

The clean layering may be:

- skills provide reusable domain patterns and authoring guidance
- task blocks provide concrete executable units in markdown
- the task runtime compiles and executes those units

That means AssistantMD could use skills to help generate and evolve task-based workflows without encoding every reusable pattern directly in the SDK.

For example:

- a research digest skill
- an inbox triage skill
- a memory-building skill
- a note classification skill

Those skills would guide generation of task blocks, not replace them.

## Relationship to Context Templates

This model does not automatically unify workflows and context templates, but it opens that possibility.

If the SDK becomes expressive enough, the same task primitives could potentially support:

- scheduled workflows
- interactive context shaping

But that should be treated as a later question, not a prerequisite.

For now, the more important goal is improving workflow authoring and generation while staying true to AssistantMD's markdown-first philosophy.

## Product Positioning

This feature should be presented as an experimental companion mode.

Suggested framing:

- current DSL remains the simplest and most human-readable workflow format
- Python task blocks are an advanced mode designed for composability and LLM-assisted generation

This avoids forcing a migration before the new mode proves its value.

## Architectural Direction

Even if the first implementation ships behind a new workflow engine name, the longer-term direction should be to reduce the importance of the "multiple workflow engines" concept rather than deepen it.

The initial rollout can still use an engine boundary for compatibility with the current loader and execution contract.

But if this experiment works, the likely direction should be:

- move the real Python-step parsing, compilation, and execution machinery into `core/workflow`
- keep any engine module as a thin compatibility shim only
- gradually extract shared workflow runtime concerns out of engine-specific code
- eventually collapse the engine distinction if the old and new paths can share one core execution model

That also creates a path to deprecate compatibility layers such as `CoreServices`, which currently exist largely to support the existing engine boundary and directive-driven runtime shape.

So the recommended mindset is:

- use a new engine name to ship safely
- do not treat "many engines forever" as the target architecture
- treat successful adoption as an opportunity to simplify workflow execution around a more central core model

## Open Questions

- Should prompts stay inline inside step blocks, or should steps be able to reference nearby markdown sections?
- How much composition should the SDK expose directly:
  - `run_step`
  - `branch`
  - `foreach`
  - simple conditionals only
- Should there be a bounded imperative escape hatch, or only declarative composition primitives?
- What is the minimum SDK surface needed to make this useful without becoming framework-heavy?
- Should the engine compile task blocks into an internal graph representation before execution?
- Should the SDK inspection tool expose raw source, parsed signatures, or both?

## Recommended Direction

AssistantMD should explore a Python-SDK-backed markdown step mode that:

- lives beside the current DSL
- keeps step definitions local and inspectable in markdown
- re-expresses the current DSL's primitives in a constrained Python SDK
- exposes that SDK directly to the LLM via inspection tooling
- validates and sandbox-tests generated tasks for automatic repair

That would preserve AssistantMD's markdown-native philosophy while materially improving the feasibility of automated workflow generation.

## Bottom Line

The strongest path forward may be:

- keep the current DSL
- add a second engine based on markdown-hosted Python step blocks
- make the SDK itself the source of truth for authoring
- give the LLM tools to inspect, validate, and sandbox-test that SDK
- if the experiment proves out, pull the real implementation into `core/workflow`, collapse engine indirection over time, and deprecate compatibility layers that no longer earn their keep

This does not abandon AssistantMD's current design.

It extends it in a direction that is more compatible with how modern LLMs actually work.
