"""Introspection helpers for the shared declarative authoring surface."""

from __future__ import annotations

import inspect
from functools import lru_cache
from pathlib import Path

from core.authoring.primitives import (
    AUTHORING_HELPER_METADATA,
    AUTHORING_HELPER_OBJECTS,
    AUTHORING_PRIMITIVE_METADATA,
    AUTHORING_PRIMITIVE_TYPES,
)


def describe_authoring_sdk() -> dict[str, object]:
    """Return structured metadata for the shared authoring primitive surface."""
    primitives: dict[str, object] = {}
    for primitive in AUTHORING_PRIMITIVE_TYPES:
        metadata = AUTHORING_PRIMITIVE_METADATA.get(primitive.__name__, {})
        methods: dict[str, object] = {}
        public_method_names = sorted(
            name
            for name, member in inspect.getmembers(primitive, predicate=callable)
            if not name.startswith("_")
        )
        for method_name in public_method_names:
            method = getattr(primitive, method_name, None)
            if method is None:
                continue
            method_docs = metadata.get("methods", {})
            methods[method_name] = {
                "signature": str(inspect.signature(method)),
                "doc": method_docs.get(method_name, inspect.getdoc(method) or ""),
            }
        primitives[primitive.__name__] = {
            "signature": str(inspect.signature(primitive)),
            "doc": inspect.getdoc(primitive) or "",
            "roles": metadata.get("roles", []),
            "constructor": metadata.get("constructor", {}),
            "methods": methods,
        }
    helpers: dict[str, object] = {}
    for helper_name, helper in AUTHORING_HELPER_OBJECTS.items():
        metadata = AUTHORING_HELPER_METADATA.get(helper_name, {})
        methods: dict[str, object] = {}
        public_method_names = sorted(
            name
            for name, member in inspect.getmembers(helper, predicate=callable)
            if not name.startswith("_")
        )
        for method_name in public_method_names:
            method = getattr(helper, method_name, None)
            if method is None:
                continue
            method_docs = metadata.get("methods", {})
            methods[method_name] = {
                "signature": str(inspect.signature(method)),
                "doc": method_docs.get(method_name, inspect.getdoc(method) or ""),
            }
        helpers[helper_name] = {
            "doc": metadata.get("doc", inspect.getdoc(helper) or ""),
            "methods": methods,
        }

    return {"primitives": primitives, "helpers": helpers}


AUTHORING_DOC_SECTIONS: dict[str, str] = {
    "overview": "Overview",
    "file_format": "File Format",
    "rules": "Rules",
}
def describe_authoring_contract() -> dict[str, object]:
    """Return the full authoring contract: wrapper guidance plus SDK metadata."""
    payload: dict[str, object] = {}
    doc_sections = _load_authoring_doc_sections()
    for section in AUTHORING_DOC_SECTIONS:
        payload[section] = doc_sections.get(section, "")
    payload.update(describe_authoring_sdk())
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
