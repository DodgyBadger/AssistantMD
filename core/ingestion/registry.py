"""
Registry for importers and extractors keyed by MIME/strategy.
"""

from typing import Any, Callable, Dict, List


ImporterFn = Callable[[Any], Any]
ExtractorFn = Callable[[Any], Any]


class Registry:
    def __init__(self):
        self._items: Dict[str, List[Callable]] = {}

    def register(self, key: str, fn: Callable) -> None:
        items = self._items.setdefault(key, [])
        items.append(fn)

    def get(self, key: str) -> List[Callable]:
        return self._items.get(key, [])


importer_registry = Registry()
extractor_registry = Registry()

