# Memory

AssistantMD memory is a structured index of chat sessions.

When you work with AssistantMD, the chat session is where the pieces of the work
come together: what you asked for, what the assistant tried, which tools were
used, which sources were read, what was produced, and which vault files were
touched. Memory gives AssistantMD a compact, searchable card for that prior work
so a future chat can find useful leads instead of searching raw transcripts
first.

The vault is still the source of truth. Memory does not replace your notes,
documents, drafts, or project files. It points back to prior sessions, the
source materials those sessions used, and, when available, the vault files those
sessions created, edited, moved, or deleted.

## What Gets Stored

A session memory record contains short derived fields:

- `summary`: durable context about what happened in the chat session
- `user_intent`: what the user was trying to accomplish
- `domain`: the subject area of the work
- `work_product`: the kind of deliverable, answer, or artifact involved
- `named_entities`: central people, organizations, and places
- `source_summary`: direct source materials read, retrieved, imported, or
  pasted into the session, with a short note about what they contributed

When AssistantMD has vault-state mutation records for the session, memory also
stores artifact pointers for files touched by that chat. These pointers include
the vault-relative path and a simple role such as `created`, `modified`,
`deleted`, `moved_from`, or `moved_to`.

The memory record is stored in AssistantMD's system database. It is derived
metadata, not a new authoritative note in the vault.

## How Memory Is Created

Memory creation is explicit and composable.

AssistantMD provides a `memory_ops` tool that can extract memory from a chat
session. A workflow can call that tool for sessions that do not yet have memory.
For example, a manually run or scheduled workflow can:

1. find sessions pending memory extraction
2. extract session memory for a limited batch
3. store the derived fields and any chat-linked artifact pointers

Users can also manually create or update memory fields through the same tool
when they want tighter control over what a session should remember.

## How Memory Is Used

AssistantMD can search session memory to find prior work that may be relevant to
the current chat. This is best understood as a structured session index, not as a
replacement for transcript or vault search.

Search results return candidate sessions, not final answers. A useful result can
tell the agent:

- what the prior session was about
- what the user was trying to do
- what kind of output was produced
- which source materials were used
- which named entities were central
- which vault files the session touched, if known

The agent can then decide whether to inspect the prior session, read linked vault
files, or ask the user for confirmation before relying on that material.

Memory search and raw transcript search work together. Memory is the first pass:
it is compact, fielded, and easier to scan. If the useful detail is not captured
in the memory card, AssistantMD can still search the full session transcript or
the vault itself.

## Context Scripts

Memory behavior is controlled by context scripts and workflows rather than a
single automatic policy.

The default context script includes a playbook for using memory. Its built-in
fallback is vault-first: once the user's work intent is clear, and before doing
external research or substantial new synthesis, the agent should ask once
whether to check prior session memory or search the vault first. If the user
agrees, the agent can use `memory_ops` to search prior sessions and
`file_ops_safe` to search or read vault files.

You can override that behavior without editing Python by adding
`AssistantMD/playbook.md` to a vault. When that file exists, the default context
script uses it instead of the built-in vault-first playbook. This lets a vault
define its own operating style, such as asking project-scoping questions first,
using memory only on request, or following a domain-specific research workflow.

This keeps memory visible and user-directed. Memory is a way to find likely
leads, not a hidden instruction layer that silently decides what the agent should
believe.

## Current Limits

Memory currently focuses on chat sessions. It works best for work that happened
through AssistantMD.

If you edit files manually in Obsidian or another editor, the vault-state worker
can observe that files changed, but those changes are not automatically attached
to a chat session. They can still be found through vault file search, but they
are not session memory unless some workflow or chat explicitly turns them into
memory.

Artifact pointers are only available when AssistantMD has task mutation records
for the chat session. Older sessions, imported sessions, or sessions from before
vault-state mutation tracking may have memory fields without artifact pointers.

Memory search is retrieval, not verification. Retrieved sessions, source
summaries, and artifacts should be treated as leads back to the vault and
transcript. The vault files and the user's judgment remain authoritative.
