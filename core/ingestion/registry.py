"""
Registry for importers and extractors keyed by MIME/strategy.
"""

from collections.abc import Callable
from typing import Any

ImporterFn = Callable[[Any], Any]
ExtractorFn = Callable[[Any], Any]


class Registry:
    def __init__(self):
        self._items: dict[str, list[Callable]] = {}

    def register(self, key: str, fn: Callable) -> None:
        items = self._items.setdefault(key, [])
        items.append(fn)

    def get(self, key: str) -> list[Callable]:
        return self._items.get(key, [])

    def keys(self) -> list[str]:
        """Return registered keys."""
        return list(self._items.keys())


importer_registry = Registry()
extractor_registry = Registry()
