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

from core.runtime.state import has_runtime_context, get_runtime_context


BUFFER_SCOPE_RUN = "run"
BUFFER_SCOPE_SESSION = "session"
VALID_BUFFER_SCOPES = {BUFFER_SCOPE_RUN, BUFFER_SCOPE_SESSION}

_fallback_session_buffers: Dict[str, "BufferStore"] = {}


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


def normalize_buffer_scope(scope: Optional[str], default_scope: str) -> str:
    candidate = (scope or "").strip().lower() or default_scope
    if candidate not in VALID_BUFFER_SCOPES:
        return default_scope
    return candidate


def get_buffer_store_for_scope(
    *,
    scope: Optional[str],
    default_scope: str,
    buffer_store: Optional[BufferStore],
    buffer_store_registry: Optional[Dict[str, BufferStore]],
) -> Optional[BufferStore]:
    resolved_scope = normalize_buffer_scope(scope, default_scope)
    if buffer_store_registry:
        return buffer_store_registry.get(resolved_scope) or buffer_store
    return buffer_store


def get_session_buffer_store(session_id: str) -> BufferStore:
    if not session_id:
        return BufferStore()
    if has_runtime_context():
        runtime = get_runtime_context()
        store = runtime.session_buffers.get(session_id)
        if store is None:
            store = BufferStore()
            runtime.session_buffers[session_id] = store
        return store
    store = _fallback_session_buffers.get(session_id)
    if store is None:
        store = BufferStore()
        _fallback_session_buffers[session_id] = store
    return store
