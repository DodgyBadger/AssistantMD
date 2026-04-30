"""
Simple frontmatter parsing utilities.

Supports flat Obsidian-style key: value properties between --- delimiters.
"""

from __future__ import annotations

import re
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
        value = _strip_unquoted_inline_comment(value).strip()
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


def _strip_unquoted_inline_comment(value: str) -> str:
    """Strip YAML-style inline comments while preserving quoted '#' characters."""
    in_single_quote = False
    in_double_quote = False

    for idx, char in enumerate(value):
        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            continue
        if char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            continue
        if char == "#" and not in_single_quote and not in_double_quote:
            return value[:idx]

    return value


def upsert_frontmatter_key(content: str, *, key: str, value: str) -> str:
    """Update or insert a frontmatter key while preserving the document body.

    Args:
        content: Full markdown document content with required frontmatter.
        key: Frontmatter key to upsert.
        value: Raw scalar value text to write (for example "true", "false", "abc").

    Returns:
        Updated full document content.

    Raises:
        ValueError: If frontmatter is missing or malformed.
    """
    if not content.startswith("---"):
        raise ValueError("File must start with YAML frontmatter")

    lines = content.splitlines(keepends=True)
    if len(lines) < 3:
        raise ValueError("Invalid frontmatter format: file too short")

    closing_index = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            closing_index = idx
            break
    if closing_index is None:
        raise ValueError("Frontmatter not properly closed with ---")

    frontmatter_lines = lines[1:closing_index]
    key_pattern = re.compile(
        rf"^(\s*{re.escape(key)}\s*:\s*)([^\n#]*)(\s*(#.*)?)$",
        re.IGNORECASE,
    )
    replaced = False
    for idx, line in enumerate(frontmatter_lines):
        line_no_newline = line.rstrip("\n")
        match = key_pattern.match(line_no_newline)
        if not match:
            continue
        newline = "\n" if line.endswith("\n") else ""
        prefix = match.group(1)
        comment = match.group(3) or ""
        frontmatter_lines[idx] = f"{prefix}{value}{comment}{newline}"
        replaced = True
        break

    if not replaced:
        newline = "\n" if frontmatter_lines and frontmatter_lines[-1].endswith("\n") else "\n"
        frontmatter_lines.append(f"{key}: {value}{newline}")

    return "".join(lines[:1] + frontmatter_lines + lines[closing_index:])
