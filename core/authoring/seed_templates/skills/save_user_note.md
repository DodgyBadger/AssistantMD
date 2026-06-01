---
name: Save User Note
description: Use when the user asks to remember, save, or persist a durable fact or preference for future chats in the vault markdown user context file.
context_notes_file: AssistantMD/user.md
context_notes_char_limit: 6000
---

Use this skill when the user explicitly asks you to remember something for
future chats, or when they confirm that a proposed user note should be
saved. This skill manages user notes in markdown. Do not use `session_ops`
for these requests; `session_ops` is for searching and summarizing prior chat
sessions.

User notes are stored as user-owned markdown at the `context_notes_file`
path in this skill's frontmatter. The default context script loads the same
file when present, bounded by `context_notes_char_limit`. Treat it as editable
vault context, not hidden authority.

## When To Save

Save a user note when:

- The user says "remember this", "save this", "for future chats", or similar.
- The user states a durable preference and explicitly wants it remembered.
- The user confirms an inferred fact or preference after you ask.

Ask before saving when the note is inferred from behavior, repeated
correction, or project context rather than directly stated.

Do not save:

- Secrets, credentials, API keys, tokens, or passwords.
- Sensitive personal data unless the user explicitly asks and the value is
  clearly useful for future chats.
- Transient task details, guesses, one-off opinions, or unverified inferences.
- Facts already better represented in a project note, source file, or other
  durable vault artifact.

## File Structure

Use this structure when creating `AssistantMD/user.md`:

```markdown
## User

- Name, role, occupation, location, and other durable user facts.

## Work Preferences

- Collaboration preferences, tooling preferences, and recurring workflow expectations.

## Projects And Domains

- Long-lived projects, domains, repositories, teams, products, or responsibilities
  the user returns to across chats.

## Candidate Notes

- Unconfirmed or possibly stale items that should not be treated as authoritative
  until reviewed.
```

Treat `Candidate Notes` as non-authoritative when using or updating context
notes. Keep confirmed notes in the topical sections above it.

## How To Update

1. Read `AssistantMD/user.md` with `file_ops_safe`.
2. If the file does not exist, create it with the structure above and the new
   context note in the best matching section.
3. Check for duplicates or contradictions before adding a bullet.
4. Prefer concise bullets over prose.
5. If a change requires rewriting or reorganizing existing content, explain the
   intended edit and ask before proceeding.
6. If the file is getting long, propose a curation pass instead of appending
   indefinitely.
