"""Shared declarative authoring surface for workflows and related systems."""

from __future__ import annotations

from importlib import import_module
from typing import Any


__all__ = [
    "compile_candidate_workflow",
]


def __getattr__(name: str) -> Any:
    if name == "compile_candidate_workflow":
        return getattr(import_module("core.authoring.service"), name)
    raise AttributeError(f"module 'core.authoring' has no attribute {name!r}")
