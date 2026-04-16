"""Generic markdown utilities shared across authoring and context surfaces."""

from __future__ import annotations

import re
from typing import Dict


def parse_markdown_sections(content: str, delimiter: str = "##") -> Dict[str, str]:
    """Extract markdown sections from content using the specified heading delimiter.

    Args:
        content: Full file content (frontmatter already stripped if present).
        delimiter: Heading prefix to split on, e.g. ``"##"`` for ``## Section``.

    Returns:
        Dictionary mapping section names to their body text (stripped).
    """
    sections: Dict[str, str] = {}
    escaped = re.escape(delimiter)
    pattern = rf"^{escaped} (.+?)\s*\n(.*?)(?=^{escaped} |\Z)"
    for section_name, section_content in re.findall(pattern, content, re.MULTILINE | re.DOTALL):
        sections[section_name] = section_content.strip()
    return sections
