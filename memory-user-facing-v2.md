# Memory

AssistantMD treats your vault as your memory system.

Your notes, project files, drafts, references, daily logs, imported documents,
and curated memory pages already live in the place where you work. AssistantMD
builds on that. It does not need a hidden memory database to replace the vault.
It needs better ways to find, connect, and reuse the knowledge already there.

## Working Sets

AssistantMD memory is about assembling the right working set.

A working set is the context the agent needs for the task at hand: relevant
notes, prior history, source files, project summaries, decisions, constraints,
recent changes, examples, or instructions. Context scripts already assemble
working sets for chat sessions. Memory expands what those scripts can draw on.

The goal is not to load more context. The goal is to assemble context that fits
the work, show what went into it, and let the user redirect when needed.

## Work Episodes

Work episodes are the bridge between memory and action.

A work episode records the shape of a piece of work: what the user was trying to
do, which files were used, which outputs were created, which people,
organizations, projects, or topics were involved, and which decisions,
objectives, or strategies mattered.

The vault remains the source of truth, but work episodes help AssistantMD find
the parts of the vault that were useful for similar work before. When a new chat
or workflow resembles prior work, AssistantMD can suggest relevant context:
source files for the same topic, format examples for the same deliverable type,
relationship notes for the same organization, or prior outputs that may serve as
models.

These suggestions are candidates, not hidden authority. A donor report about one
topic may share a useful format with another donor report, while a funding
proposal about the same topic may share source material but need a different
strategy. AssistantMD should explain why prior work looks relevant and let the
user decide what belongs in the current working set.

## Vault Awareness

The long-term goal is vault awareness.

AssistantMD should be able to build and maintain maps of the vault, or of a
scoped slice of the vault: a project folder, a research area, a workflow domain,
or a curated memory namespace. These maps help the agent understand what exists,
what is active, what may be authoritative, what may be stale, and how files
relate to each other.

This does not mean summarizing the entire vault into one giant document. It means
maintaining enough structured, inspectable context that AssistantMD can answer
questions like:

- What is this vault area about?
- What work has happened here before?
- Which notes or outputs were useful for similar work?
- What projects, people, organizations, or topics are involved?
- What changed recently?
- What decisions or constraints have been recorded?
- What sources support this answer?
- Which areas look stale, duplicated, contradictory, or incomplete?

Another way to think about this is maps and wayfinding. AssistantMD can use
different maps of the same vault, such as recent activity, source notes,
decisions, open questions, links, work episodes, or trust status, to assemble a
working set. It should be able to show which route it used and suggest other ways
to explore the same knowledge.

## Trust

Most files in the vault are treated as source material: they are part of your
working knowledge, not just data to be summarized away. When AssistantMD creates
derived files such as summaries, reports, imports, captured memory, or work
episode notes, those files remain visible markdown artifacts in the vault. You
can inspect them, edit them, move them, or delete them.

Generated memory starts as supporting evidence unless you review or confirm it
as guidance. A work episode can suggest that a file, decision, or strategy was
useful before, but it should not silently make that material authoritative for
new work. The vault remains the source of truth.

Short version:

> Your vault is the memory. Work episodes help AssistantMD find the right parts
> of it for the task at hand.
