"""Introspection helpers for the shared declarative authoring surface."""

from __future__ import annotations

import inspect

from core.authoring.primitives import (
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
    return {"primitives": primitives}
