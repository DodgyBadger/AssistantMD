"""
Markdown chunk parser for ordered text/image parts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Literal, Optional


ChunkKind = Literal["text", "image_ref"]

_IMAGE_TOKEN_PATTERN = re.compile(
    r"!\[([^\]]*)\]\(([^)]+)\)|!\[\[([^\]]+)\]\]"
)


@dataclass(frozen=True)
class MarkdownChunk:
    kind: ChunkKind
    text: str = ""
    image_ref: Optional[str] = None
    alt_text: Optional[str] = None
    start: int = 0
    end: int = 0


def _normalize_markdown_target(raw_target: str) -> str:
    target = (raw_target or "").strip()
    if not target:
        return ""

    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()

    if " " in target and not target.startswith(("http://", "https://")):
        target = target.split(" ", 1)[0].strip()

    if "|" in target:
        target = target.split("|", 1)[0].strip()
    if "#" in target:
        target = target.split("#", 1)[0].strip()
    return target


def parse_markdown_chunks(markdown_text: str) -> List[MarkdownChunk]:
    """
    Parse markdown into ordered text and image-ref chunks.

    Supports:
    - Standard markdown image tags: ![alt](path)
    - Obsidian embeds: ![[path]]
    """
    if not markdown_text:
        return []

    chunks: List[MarkdownChunk] = []
    cursor = 0
    for match in _IMAGE_TOKEN_PATTERN.finditer(markdown_text):
        start, end = match.span()
        if start > cursor:
            text = markdown_text[cursor:start]
            if text:
                chunks.append(
                    MarkdownChunk(
                        kind="text",
                        text=text,
                        start=cursor,
                        end=start,
                    )
                )

        md_alt = match.group(1)
        md_target = match.group(2)
        wiki_target = match.group(3)
        raw_target = md_target if md_target is not None else (wiki_target or "")
        normalized_target = _normalize_markdown_target(raw_target)
        if normalized_target:
            chunks.append(
                MarkdownChunk(
                    kind="image_ref",
                    image_ref=normalized_target,
                    alt_text=(md_alt or "").strip() if md_alt is not None else None,
                    start=start,
                    end=end,
                )
            )
        else:
            chunks.append(
                MarkdownChunk(
                    kind="text",
                    text=match.group(0),
                    start=start,
                    end=end,
                )
            )
        cursor = end

    if cursor < len(markdown_text):
        tail = markdown_text[cursor:]
        if tail:
            chunks.append(
                MarkdownChunk(
                    kind="text",
                    text=tail,
                    start=cursor,
                    end=len(markdown_text),
                )
            )

    return chunks

