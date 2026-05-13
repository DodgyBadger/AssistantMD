# Memory

AssistantMD treats your vault as your memory system. Memory is not a separate
place where facts are stored; it is a way to build better working sets from the
vault.

Your notes, project files, drafts, references, daily logs, imported documents,
and curated memory pages already live in the place where you work. AssistantMD
builds on that. It can help find relevant files, summarize what matters, capture
decisions, update project notes, and assemble context for chats or workflows.

A working set is the context the agent needs for the task at hand: relevant
notes, prior history, source files, project summaries, decisions, constraints,
recent changes, or instructions. Context scripts already assemble working sets
for chat sessions. Memory and vault awareness expand what those scripts can draw
on.

Most files in the vault are treated as source material: they are part of your
working knowledge, not just data to be summarized away. When AssistantMD creates
derived files such as summaries, reports, imports, or captured memory, those
files remain visible markdown artifacts in the vault. You can inspect them,
edit them, move them, or delete them.

The goal is transparent memory. AssistantMD should be able to show what it used,
where it came from, and whether it is user-authored, imported, or generated.
Generated memory starts as supporting evidence unless you review or confirm it
as guidance. The vault remains the source of truth.

Short version:

> Your vault is the memory. AssistantMD helps assemble the right working set.

## Vault Awareness

The long-term goal is vault awareness.

AssistantMD should be able to build and maintain maps of the vault, or of a
scoped slice of the vault: a project folder, a research area, a workflow domain,
or a curated memory namespace. Those maps should help the agent understand what
exists, what is active, what is authoritative, what is stale, and how files
relate to each other.

This does not mean summarizing the entire vault into one giant document. It means
maintaining enough structured, inspectable context that AssistantMD can answer
questions like:

- What is this vault about?
- What projects are active?
- Which notes look central or authoritative?
- What changed recently?
- What decisions or constraints have been recorded?
- What sources support this answer?
- Which areas look stale, duplicated, contradictory, or incomplete?

The user should be able to scope that awareness. A chat might ask for awareness
of one project folder. A workflow might maintain an overview of imported research.
A context script might retrieve only confirmed memory notes. The vault remains
the source of truth, and these maps are derived aids for navigation, recall, and
working-set assembly.

Another way to think about this is maps and wayfinding. AssistantMD can use
different maps of the same vault, such as recent activity, source notes,
decisions, open questions, links, or trust status, to assemble a working set. It
should be able to show which route it used and suggest other ways to explore the
same knowledge.
