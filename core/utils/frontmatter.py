"""
Simple frontmatter parsing utilities.

Supports flat Obsidian-style key: value properties between --- delimiters.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple


def parse_simple_frontmatter(
    content: str,
    *,
    require_frontmatter: bool = False,
    missing_error: str = "File must start with YAML frontmatter (---)",
) -> Tuple[Dict[str, Any], str]:
    """Parse flat key:value frontmatter and return (properties, remaining_content)."""
    normalized = (content or "").strip()

    if not normalized.startswith("---"):
        if require_frontmatter:
            raise ValueError(missing_error)
        return {}, content

    lines = normalized.split("\n")
    if len(lines) < 3:
        raise ValueError("Invalid frontmatter format: file too short")

    end_idx = None
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        raise ValueError("Frontmatter not properly closed with ---")

    properties: Dict[str, Any] = {}
    for line_num, line in enumerate(lines[1:end_idx], 2):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"Line {line_num}: Invalid format, expected 'key: value'")

        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise ValueError(f"Line {line_num}: Empty key not allowed")

        if len(value) >= 2:
            if (value[0] == '"' and value[-1] == '"') or (value[0] == "'" and value[-1] == "'"):
                value = value[1:-1]

        lowered = value.lower()
        if lowered in ("true", "yes", "on"):
            properties[key] = True
        elif lowered in ("false", "no", "off"):
            properties[key] = False
        else:
            properties[key] = value

    remaining_content = "\n".join(lines[end_idx + 1 :])
    return properties, remaining_content
