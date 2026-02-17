# Context Manager Subsystem

Context Manager controls what chat history/context is passed to the chat agent, using templates and step-based summarization/curation.

## Primary code

- `core/context/manager.py`
- `core/context/manager_helpers.py`
- `core/context/templates.py`
- `core/context/store.py`

## Responsibilities

- Load context templates with vault -> system precedence.
- Parse template sections and directives.
- Execute context-manager sections in order.
- Inject selected section output into chat-agent system context.
- Persist managed summaries for later reuse.

## Template model

- `## Chat Instructions`: pass through to chat agent.
- `## Context Instructions`: instructions for context-manager runs.
- Other `##` sections: context-manager steps.
- Sections can use directive controls (`@recent_runs`, `@recent_summaries`, `@tools`, `@model`, `@cache`, outputs/routing).

## Runtime behavior

- If template has no executable sections, manager can pass through chat instructions/history directly.
- Token-threshold gating can skip manager execution for short histories.
- Section outputs only affect chat context when routed to `context`.
