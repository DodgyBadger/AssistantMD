"""Introspection helpers for the current declarative authoring surface."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from core.authoring.builtins import create_builtin_registry


def describe_authoring_capabilities() -> dict[str, object]:
    """Return structured metadata for experimental built-in authoring capabilities."""
    registry = create_builtin_registry()
    capabilities: dict[str, object] = {}
    for name in registry.list_names():
        definition = registry.resolve(name)
        capabilities[name] = {
            "doc": definition.doc,
            "contract": definition.contract,
        }
    return {"capabilities": capabilities}


AUTHORING_DOC_SECTIONS: dict[str, str] = {
    "overview": "Overview",
    "file_format": "File Format",
    "rules": "Rules",
}
def describe_authoring_contract() -> dict[str, object]:
    """Return the full current authoring contract."""
    payload: dict[str, object] = {}
    doc_sections = _load_authoring_doc_sections()
    for section in AUTHORING_DOC_SECTIONS:
        payload[section] = doc_sections.get(section, "")
    payload.update(describe_authoring_capabilities())
    return payload


@lru_cache(maxsize=1)
def _load_authoring_doc_sections() -> dict[str, str]:
    """Load authoring guide prose sections from docs/use/authoring.md."""
    doc_path = Path(__file__).resolve().parents[2] / "docs" / "use" / "authoring.md"
    content = doc_path.read_text(encoding="utf-8")

    sections: dict[str, str] = {}
    for key, heading in AUTHORING_DOC_SECTIONS.items():
        marker = f"## {heading}"
        start = content.find(marker)
        if start == -1:
            sections[key] = ""
            continue
        body_start = start + len(marker)
        next_heading = content.find("\n## ", body_start)
        section_text = content[body_start:] if next_heading == -1 else content[body_start:next_heading]
        sections[key] = section_text.strip()
    return sections
