"""
Run-scoped buffer store for virtualized I/O.

Mental model:
- BufferStore is the in-memory container.
- Entries inside it are named variables.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass
class BufferEntry:
    """Single variable entry stored inside the buffer."""
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BufferStore:
    """Simple in-memory container for named variables."""

    def __init__(self) -> None:
        self._buffers: Dict[str, BufferEntry] = {}

    def put(
        self,
        name: str,
        content: str,
        *,
        mode: str = "replace",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not name or not name.strip():
            raise ValueError("Variable name is required")
        if mode not in {"replace", "append"}:
            raise ValueError("Buffer mode must be 'replace' or 'append'")
        now = datetime.now(timezone.utc)
        meta = metadata or {}
        if name in self._buffers and mode == "append":
            entry = self._buffers[name]
            entry.content = (entry.content or "") + (content or "")
            entry.metadata.update(meta)
            entry.updated_at = now
            return
        self._buffers[name] = BufferEntry(
            content=content or "",
            metadata=dict(meta),
            created_at=now,
            updated_at=now,
        )

    def get(self, name: str) -> Optional[BufferEntry]:
        if not name:
            return None
        return self._buffers.get(name)

    def list(self) -> Dict[str, Dict[str, Any]]:
        return {
            name: {
                "size": len(entry.content or ""),
                "created_at": entry.created_at,
                "updated_at": entry.updated_at,
                "metadata": dict(entry.metadata),
            }
            for name, entry in self._buffers.items()
        }

    def clear(self, name: str) -> bool:
        if not name:
            return False
        return self._buffers.pop(name, None) is not None

    def clear_all(self) -> None:
        self._buffers.clear()
