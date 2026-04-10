# Tool Documentation Disclosure Spec

## Summary

AssistantMD should move toward a documentation-first disclosure model for tools and authoring surfaces.

The goal is to keep always-present tool context small, let the LLM discover richer documentation on demand, and avoid maintaining a separate special-case metadata channel that breaks the pattern.

This applies to:

- chat tools
- `code_execution_local`
- Monty authoring helpers and built-ins

## Problem

We currently have multiple competing documentation layers:

- thin tool descriptions in the system prompt
- per-tool instruction text
- special no-arg tool discovery behavior
- the authoring contract endpoint

This creates context-management problems:

- large payloads are easy to surface accidentally
- new capabilities can be buried in large responses
- some tools behave differently from others
- the authoring endpoint introduces a second disclosure path that does not match the rest of the tool system

`code_execution_local` is the clearest example:

- generic wrapper behavior wants no-arg calls to return instructions
- the tool itself tried to return the full authoring contract payload
- the result is inconsistent and too large to be useful as first-step discovery

## Decision

Adopt a documentation-first disclosure model centered on `__virtual_docs__`.

The intended model is:

1. System prompt includes only thin tool descriptions.
2. Rich documentation lives in markdown docs exposed through `__virtual_docs__`.
3. The LLM uses `file_ops_safe` to search and read only the docs it needs.
4. Tool no-arg responses stay brief and operational, or may eventually disappear as a major documentation channel.
5. Special metadata endpoints should not be the primary LLM-facing documentation surface.

## Desired Disclosure Layers

### 1. Thin Prompt Descriptions

Each tool should contribute only:

- tool name
- one short description
- enough signal for the model to decide whether to use it

This keeps always-on context small.

### 2. Rich Docs In `__virtual_docs__`

Tool docs should live in markdown and be readable with `file_ops_safe`.

The model should be able to:

- list docs
- search docs for a tool or concept
- open a specific relevant doc
- read only the needed section

This should be the main discovery path for deeper usage guidance.

Tool docs should also carry preference guidance where it materially affects efficiency or stability.

Example:

- for web research, prefer `tavily_extract` first when the URL is known and simple extraction is likely sufficient
- use `browser` only when extraction fails, returns thin content, or the page is clearly JavaScript-heavy

These preference rules should live in docs instead of being repeated inconsistently across prompt layers.

### 3. Exact Contract Documentation

For authoring and helper surfaces, the exact callable contract should also be documented in the docs corpus.

This can include:

- signatures
- examples
- return shapes
- caveats

It should still be documentation-first, not endpoint-first.

## Implication For `code_execution_local`

`code_execution_local` should stop trying to surface the full authoring contract by default.

Instead:

- its tool description stays thin
- its no-arg discovery, if retained, should be brief
- deeper Monty/helper guidance should live in virtual docs

The model can then:

1. decide it needs local code execution
2. call `file_ops_safe` to search docs for Monty authoring or helper usage
3. read the relevant docs
4. write the code

This is more consistent than embedding a large contract dump in the tool itself.

## Implication For The Authoring Endpoint

If AssistantMD fully adopts the virtual-docs pattern, the authoring endpoint should be deprecated as an LLM-facing documentation mechanism.

This is the logical conclusion of the design direction.

Why:

- it breaks the otherwise consistent docs-discovery pattern
- it introduces a second documentation channel
- it encourages large structured payloads where targeted docs would work better

This does not necessarily mean the endpoint must disappear immediately.

Possible transition options:

- keep it temporarily for internal/debug use
- stop surfacing it through tool flows
- eventually remove it if docs fully replace the need

## Why This Direction Fits AssistantMD

AssistantMD is markdown-first and single-user. The simplest durable pattern is:

- store docs as markdown
- let the model read docs like any other artifact
- avoid over-engineered tool metadata protocols unless they provide clear value

This also aligns with the broader philosophy behind deferred tool disclosure:

- keep initial context small
- load richer information only when needed

## Non-Goals

This spec does not require:

- building a dedicated tool-search subsystem immediately
- exposing every tool instruction through new structured params
- preserving the current authoring endpoint as a first-class model-facing surface

`file_ops_safe` over `__virtual_docs__` is sufficient as the initial targeted-disclosure mechanism.

## Initial Follow-Up Work

1. Audit current tool discovery behavior and remove oversized or conflicting no-arg disclosure paths.
2. Create or normalize virtual docs for the main tools and Monty authoring helpers.
3. Ensure `file_ops_safe` can search and read virtual docs cleanly.
4. Stop relying on the authoring endpoint from `code_execution_local`.
5. Define a deprecation plan for the authoring endpoint as an LLM-facing documentation channel.
6. Perform a comprehensive audit of all prompt-injection surfaces to make sure tool and documentation disclosure stays consistent across the system.

Areas that need explicit review include at least:

- `core/constants.py`
- the default context template
- tool summary assembly
- tool no-arg discovery behavior
- code mode/tool mode prompt layers
- any other runtime-assembled system or helper prompt blocks

## Open Questions

- Should no-arg tool calls remain as short operational hints, or should documentation live entirely in virtual docs?
- Do we want a lightweight docs index file in `__virtual_docs__` to improve discoverability?
- Should exact built-in contracts be rendered from code into markdown automatically, or maintained manually?
