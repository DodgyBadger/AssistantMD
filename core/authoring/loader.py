"""Markdown template loading for the experimental Monty-backed authoring surface."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.utils.frontmatter import parse_simple_frontmatter


_PYTHON_BLOCK_PATTERN = re.compile(r"```python\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)
_HEADING_PATTERN = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class AuthoringTemplateSource:
    """Parsed markdown template source for Monty execution."""

    frontmatter: dict[str, Any]
    code: str
    block_count: int
    block_label: str | None
    body: str


def load_authoring_template_file(file_path: str | Path) -> AuthoringTemplateSource:
    """Read and parse one markdown template file."""
    content = Path(file_path).read_text(encoding="utf-8")
    return parse_authoring_template_text(content)


def parse_authoring_template_text(content: str) -> AuthoringTemplateSource:
    """Parse frontmatter and exactly one fenced python block from markdown text."""
    frontmatter, body = parse_simple_frontmatter(content, require_frontmatter=False)
    matches = list(_PYTHON_BLOCK_PATTERN.finditer(body))
    if not matches:
        raise ValueError("Authoring template must include exactly one fenced ```python``` block")
    if len(matches) > 1:
        raise ValueError("Authoring template supports exactly one fenced ```python``` block")

    match = matches[0]
    code = match.group(1).strip()
    if not code:
        raise ValueError("Authoring template python block must not be empty")

    block_label = _nearest_heading(body, match.start())
    return AuthoringTemplateSource(
        frontmatter=frontmatter,
        code=code,
        block_count=1,
        block_label=block_label,
        body=body,
    )


def _nearest_heading(body: str, block_start: int) -> str | None:
    """Return the closest preceding markdown heading label for the python block."""
    label: str | None = None
    for match in _HEADING_PATTERN.finditer(body):
        if match.start() >= block_start:
            break
        label = match.group(1).strip()
    return label
