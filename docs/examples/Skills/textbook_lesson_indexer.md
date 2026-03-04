---
title: Textbook Lesson Indexer
description: Build a lesson index from sequential page images using a cursor-driven batch process.
---

## Purpose
Build an index so future chats can jump to the right page image based on lesson/topic.

## Files
- Pages folder: Imported/my-textbook/pages/
- Index file: Imported/my-textbook/index/lessons_index.md
- State file: Imported/my-textbook/index/index_state.md

## Index entry format (use exactly)

### <Unit> - Lesson #<n>: <Title>
- start_image: page_####.png
- end_image: page_####.png (leave blank until next lesson is discovered)
- synopsis: 1-2 sentences

## Rules
- Only create entries when a page clearly indicates a new lesson/unit
- No duplicates
- Do not rewrite existing entries except to fill end_image or fix OCR errors
- Keep synopsis to 1-2 sentences

## Batch procedure
1. Read state file for next_page and batch_size (create with defaults if missing).
2. Compute the next batch of filenames (page_0001.png, page_0002.png, etc.).
3. Read only those images.
4. Update the index with any new lesson starts found.
5. Set end_image on the previous entry only when a new lesson start is found.
6. Advance next_page in the state file.

## Response style
After updating files, report: scanned range, new entries added, which pages.
