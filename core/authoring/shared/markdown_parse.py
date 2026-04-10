"""Structured markdown parsing helpers for authoring surfaces."""

from __future__ import annotations

from typing import Any

from markdown_it import MarkdownIt

from core.authoring.contracts import (
    MarkdownCodeBlock,
    MarkdownHeading,
    MarkdownImage,
    MarkdownSection,
    ParsedMarkdown,
)
from core.utils.frontmatter import parse_simple_frontmatter


_MARKDOWN_PARSER = MarkdownIt()
def parse_markdown_content(value: str) -> ParsedMarkdown:
    """Parse markdown text into a small structured representation."""
    frontmatter, body = parse_simple_frontmatter(value or "")
    tokens = _MARKDOWN_PARSER.parse(body)
    body_lines = body.splitlines()

    headings = _extract_headings(tokens)
    sections = _extract_sections(headings, body_lines)
    code_blocks = _extract_code_blocks(tokens)
    images = _extract_images(tokens)

    return ParsedMarkdown(
        frontmatter=dict(frontmatter),
        body=body,
        headings=tuple(headings),
        sections=tuple(sections),
        code_blocks=tuple(code_blocks),
        images=tuple(images),
    )


def _extract_headings(tokens: list[Any]) -> list[MarkdownHeading]:
    headings: list[MarkdownHeading] = []
    for index, token in enumerate(tokens):
        if token.type != "heading_open":
            continue
        level = _parse_heading_level(token.tag)
        if level is None:
            continue
        if index + 1 >= len(tokens) or tokens[index + 1].type != "inline":
            continue
        inline = tokens[index + 1]
        text = str(getattr(inline, "content", "") or "")
        map_value = getattr(token, "map", None) or [0, 0]
        line_start = int(map_value[0]) + 1
        headings.append(
            MarkdownHeading(
                level=level,
                text=text,
                line_start=line_start,
            )
        )
    return headings


def _extract_sections(
    headings: list[MarkdownHeading],
    body_lines: list[str],
) -> list[MarkdownSection]:
    if not headings:
        return []

    sections: list[MarkdownSection] = []
    for index, heading in enumerate(headings):
        start_index = max(heading.line_start, 1)
        next_heading_line = headings[index + 1].line_start if index + 1 < len(headings) else len(body_lines) + 1
        content = "\n".join(body_lines[start_index: max(next_heading_line - 1, start_index)]).strip("\n")
        sections.append(
            MarkdownSection(
                heading=heading.text,
                level=heading.level,
                content=content,
                line_start=heading.line_start,
            )
        )
    return sections


def _extract_code_blocks(tokens: list[Any]) -> list[MarkdownCodeBlock]:
    blocks: list[MarkdownCodeBlock] = []
    for token in tokens:
        if token.type != "fence":
            continue
        map_value = getattr(token, "map", None)
        line_start = int(map_value[0]) + 1 if map_value else None
        info = str(getattr(token, "info", "") or "").strip()
        language = info.split()[0] if info else None
        blocks.append(
            MarkdownCodeBlock(
                language=language or None,
                content=str(getattr(token, "content", "") or ""),
                line_start=line_start,
            )
        )
    return blocks


def _extract_images(tokens: list[Any]) -> list[MarkdownImage]:
    images: list[MarkdownImage] = []
    current_line_start: int | None = None

    for token in tokens:
        map_value = getattr(token, "map", None)
        if map_value:
            current_line_start = int(map_value[0]) + 1

        children = getattr(token, "children", None) or ()
        for child in children:
            if child.type != "image":
                continue
            attrs = dict(getattr(child, "attrs", {}) or {})
            images.append(
                MarkdownImage(
                    src=str(attrs.get("src") or ""),
                    alt=str(getattr(child, "content", "") or ""),
                    title=_normalize_optional_string(attrs.get("title")),
                    line_start=current_line_start,
                )
            )
    return images


def _parse_heading_level(tag: str) -> int | None:
    if tag.startswith("h") and tag[1:].isdigit():
        return int(tag[1:])
    return None


def _normalize_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
