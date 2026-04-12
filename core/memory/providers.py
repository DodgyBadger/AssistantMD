"""Source-agnostic conversation history providers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from pydantic_ai.messages import ModelMessage

from core.context.manager_helpers import extract_role_and_text, run_slice


@dataclass(frozen=True)
class ConversationHistoryItem:
    """One normalized conversation history item."""

    role: str
    content: str
    session_id: str | None = None
    run_id: str | None = None
    message_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConversationHistoryResult:
    """Structured result from a conversation history lookup."""

    source: str
    scope: str
    session_id: str | None
    item_count: int
    items: tuple[ConversationHistoryItem, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Render as a plain dictionary suitable for JSON serialization."""
        return {
            "source": self.source,
            "scope": self.scope,
            "session_id": self.session_id,
            "item_count": self.item_count,
            "items": [asdict(item) for item in self.items],
        }


class ConversationHistoryProvider(Protocol):
    """Source-agnostic provider for conversation history."""

    source_name: str

    def get_history(
        self,
        *,
        scope: str,
        session_id: str | None = None,
        limit: int | str = "all",
    ) -> ConversationHistoryResult: ...


@dataclass(frozen=True)
class InMemoryConversationHistoryProvider:
    """Conversation history provider backed by the current in-memory chat state."""

    message_history: tuple[ModelMessage, ...]
    active_session_id: str | None = None

    source_name: str = "in_memory"

    def get_history(
        self,
        *,
        scope: str,
        session_id: str | None = None,
        limit: int | str = "all",
    ) -> ConversationHistoryResult:
        normalized_scope = (scope or "").strip().lower() or "session"
        if normalized_scope != "session":
            raise ValueError("memory_ops currently supports only scope='session'")

        requested_session_id = (session_id or "").strip() or self.active_session_id
        if session_id and self.active_session_id and session_id != self.active_session_id:
            raise ValueError(
                "The current memory provider only exposes the active in-memory chat session"
            )

        if limit == "all":
            selected = list(self.message_history)
        else:
            selected = run_slice(list(self.message_history), limit)

        items = tuple(
            _normalize_message(message, session_id=requested_session_id) for message in selected
        )
        return ConversationHistoryResult(
            source=self.source_name,
            scope=normalized_scope,
            session_id=requested_session_id,
            item_count=len(items),
            items=items,
        )


def resolve_conversation_history_provider(
    *,
    message_history: list[ModelMessage] | tuple[ModelMessage, ...] | None,
    session_id: str | None,
) -> ConversationHistoryProvider:
    """Resolve the active conversation history provider for the current runtime context."""
    return InMemoryConversationHistoryProvider(
        message_history=tuple(message_history or ()),
        active_session_id=session_id,
    )


def _normalize_message(
    message: ModelMessage,
    *,
    session_id: str | None,
) -> ConversationHistoryItem:
    role, content = extract_role_and_text(message)
    run_id = getattr(message, "run_id", None)
    return ConversationHistoryItem(
        role=role,
        content=content,
        session_id=session_id,
        run_id=run_id,
        message_type=type(message).__name__,
        metadata={
            "role": role,
            "run_id": run_id,
            "message_type": type(message).__name__,
        },
    )
