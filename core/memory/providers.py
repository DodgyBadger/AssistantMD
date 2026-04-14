"""Source-agnostic conversation history providers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from pydantic import TypeAdapter
from pydantic_ai.messages import ModelMessage

from core.chat import ChatStore
from core.context.manager_helpers import extract_role_and_text, run_slice


_MODEL_MESSAGE_ADAPTER = TypeAdapter(ModelMessage)


@dataclass(frozen=True)
class ConversationHistoryItem:
    """One normalized conversation history item."""

    role: str
    content: str
    session_id: str | None = None
    run_id: str | None = None
    message_type: str | None = None
    sequence_index: int | None = None
    direction: str | None = None
    message: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConversationHistoryResult:
    """Structured result from a conversation history lookup."""

    source: str
    scope: str
    session_id: str | None
    item_count: int
    items: tuple[ConversationHistoryItem, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Render as a plain dictionary suitable for JSON serialization."""
        return {
            "source": self.source,
            "scope": self.scope,
            "session_id": self.session_id,
            "item_count": self.item_count,
            "items": [asdict(item) for item in self.items],
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class ConversationToolEventItem:
    """One normalized structured tool event item."""

    tool_call_id: str
    tool_name: str
    event_type: str
    created_at: str | None = None
    args: dict[str, Any] | None = None
    result_text: str | None = None
    result_metadata: dict[str, Any] = field(default_factory=dict)
    artifact_ref: str | None = None


@dataclass(frozen=True)
class ConversationToolEventResult:
    """Structured result from a tool-event lookup."""

    source: str
    scope: str
    session_id: str | None
    item_count: int
    items: tuple[ConversationToolEventItem, ...] = ()

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
        message_filter: str = "all",
    ) -> ConversationHistoryResult: ...

    def get_tool_events(
        self,
        *,
        scope: str,
        session_id: str | None = None,
        limit: int | str = "all",
    ) -> ConversationToolEventResult: ...


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
        message_filter: str = "all",
    ) -> ConversationHistoryResult:
        normalized_scope = (scope or "").strip().lower() or "session"
        if normalized_scope != "session":
            raise ValueError("memory_ops currently supports only scope='session'")
        normalized_filter = _normalize_message_filter(message_filter)

        requested_session_id = (session_id or "").strip() or self.active_session_id
        if session_id and self.active_session_id and session_id != self.active_session_id:
            raise ValueError(
                "The current memory provider only exposes the active in-memory chat session"
            )

        if limit == "all":
            selected = list(self.message_history)
        else:
            selected = run_slice(list(self.message_history), limit)
        selected = _filter_messages(selected, normalized_filter)

        items = tuple(
            _normalize_message(message, session_id=requested_session_id) for message in selected
        )
        return ConversationHistoryResult(
            source=self.source_name,
            scope=normalized_scope,
            session_id=requested_session_id,
            item_count=len(items),
            items=items,
            metadata={"canonical_source": "message_history", "message_filter": normalized_filter},
        )

    def get_tool_events(
        self,
        *,
        scope: str,
        session_id: str | None = None,
        limit: int | str = "all",
    ) -> ConversationToolEventResult:
        normalized_scope = (scope or "").strip().lower() or "session"
        if normalized_scope != "session":
            raise ValueError("memory_ops currently supports only scope='session'")
        del limit
        requested_session_id = (session_id or "").strip() or self.active_session_id
        return ConversationToolEventResult(
            source=self.source_name,
            scope=normalized_scope,
            session_id=requested_session_id,
            item_count=0,
            items=(),
        )


@dataclass(frozen=True)
class SQLiteConversationHistoryProvider:
    """Conversation history provider backed by persisted chat session state."""

    store: ChatStore
    vault_name: str
    active_session_id: str | None = None

    source_name: str = "sqlite_chat_sessions"

    def get_history(
        self,
        *,
        scope: str,
        session_id: str | None = None,
        limit: int | str = "all",
        message_filter: str = "all",
    ) -> ConversationHistoryResult:
        normalized_scope = (scope or "").strip().lower() or "session"
        if normalized_scope != "session":
            raise ValueError("memory_ops currently supports only scope='session'")
        normalized_filter = _normalize_message_filter(message_filter)

        requested_session_id = (session_id or "").strip() or self.active_session_id
        if not requested_session_id:
            return ConversationHistoryResult(
                source=self.source_name,
                scope=normalized_scope,
                session_id=None,
                item_count=0,
                items=(),
                metadata={"canonical_source": "chat_messages", "message_filter": normalized_filter},
            )

        stored_messages = self.store.get_stored_messages(requested_session_id, self.vault_name)
        stored_messages = _filter_stored_messages(stored_messages, normalized_filter)
        if limit != "all":
            stored_messages = stored_messages[-limit:]

        items = tuple(
            _normalize_stored_message(message, session_id=requested_session_id)
            for message in stored_messages
        )
        return ConversationHistoryResult(
            source=self.source_name,
            scope=normalized_scope,
            session_id=requested_session_id,
            item_count=len(items),
            items=items,
            metadata={"canonical_source": "chat_messages", "message_filter": normalized_filter},
        )

    def get_tool_events(
        self,
        *,
        scope: str,
        session_id: str | None = None,
        limit: int | str = "all",
    ) -> ConversationToolEventResult:
        normalized_scope = (scope or "").strip().lower() or "session"
        if normalized_scope != "session":
            raise ValueError("memory_ops currently supports only scope='session'")

        requested_session_id = (session_id or "").strip() or self.active_session_id
        if not requested_session_id:
            return ConversationToolEventResult(
                source=self.source_name,
                scope=normalized_scope,
                session_id=None,
                item_count=0,
                items=(),
            )

        resolved_limit = None if limit == "all" else limit
        events = self.store.get_tool_events(
            requested_session_id,
            self.vault_name,
            limit=resolved_limit,
        )
        items = tuple(_normalize_tool_event(event) for event in events)
        return ConversationToolEventResult(
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
    vault_name: str | None,
) -> ConversationHistoryProvider:
    """Resolve the active conversation history provider for the current runtime context."""
    normalized_session_id = (session_id or "").strip() or None
    normalized_vault_name = (vault_name or "").strip() or None
    if normalized_session_id and normalized_vault_name:
        store = ChatStore()
        if store.get_message_count(normalized_session_id, normalized_vault_name) > 0:
            return SQLiteConversationHistoryProvider(
                store=store,
                vault_name=normalized_vault_name,
                active_session_id=normalized_session_id,
            )
    return InMemoryConversationHistoryProvider(
        message_history=tuple(message_history or ()),
        active_session_id=normalized_session_id,
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
        message=_dump_message_payload(message),
        metadata={
            "role": role,
            "run_id": run_id,
            "message_type": type(message).__name__,
        },
    )


def _normalize_stored_message(message, *, session_id: str | None) -> ConversationHistoryItem:
    run_id = getattr(message.message, "run_id", None)
    return ConversationHistoryItem(
        role=message.role,
        content=message.content_text,
        session_id=session_id,
        run_id=run_id,
        message_type=message.message_type,
        sequence_index=message.sequence_index,
        direction=message.direction,
        message=_load_json_value(message.message_json) or {},
        metadata={
            "role": message.role,
            "run_id": run_id,
            "message_type": message.message_type,
            "sequence_index": message.sequence_index,
            "direction": message.direction,
            "created_at": message.created_at,
        },
    )


def _normalize_message_filter(message_filter: str) -> str:
    normalized = (message_filter or "").strip().lower() or "all"
    if normalized not in {"all", "exclude_tools", "only_tools"}:
        raise ValueError("message_filter must be one of: all, exclude_tools, only_tools")
    return normalized


def _filter_messages(messages: list[ModelMessage], message_filter: str) -> list[ModelMessage]:
    if message_filter == "all":
        return list(messages)
    if message_filter == "exclude_tools":
        return [message for message in messages if not _message_has_tool_parts(message)]
    return [message for message in messages if _message_has_tool_parts(message)]


def _filter_stored_messages(messages: list[Any], message_filter: str) -> list[Any]:
    if message_filter == "all":
        return list(messages)
    if message_filter == "exclude_tools":
        return [message for message in messages if not _message_has_tool_parts(message.message)]
    return [message for message in messages if _message_has_tool_parts(message.message)]


def _message_has_tool_parts(message: ModelMessage) -> bool:
    for part in getattr(message, "parts", ()) or ():
        if getattr(part, "part_kind", None) in {"tool-call", "tool-return"}:
            return True
    return False


def _normalize_tool_event(event) -> ConversationToolEventItem:
    return ConversationToolEventItem(
        tool_call_id=event.tool_call_id,
        tool_name=event.tool_name,
        event_type=event.event_type,
        created_at=event.created_at or None,
        args=_load_json_object(event.args_json),
        result_text=event.result_text,
        result_metadata=_load_json_object(event.result_metadata_json) or {},
        artifact_ref=event.artifact_ref,
    )


def _load_json_object(raw_value: str | None) -> dict[str, Any] | None:
    if not raw_value:
        return None
    try:
        parsed = json.loads(raw_value)
    except Exception:
        return {"raw": raw_value}
    if isinstance(parsed, dict):
        return parsed
    return {"value": parsed}


def _load_json_value(raw_value: str | None) -> Any:
    if not raw_value:
        return None
    try:
        return json.loads(raw_value)
    except Exception:
        return raw_value


def _dump_message_payload(message: ModelMessage) -> dict[str, Any] | None:
    try:
        payload = _MODEL_MESSAGE_ADAPTER.dump_python(message, mode="json")
    except Exception:
        return None
    return payload if isinstance(payload, dict) else {"value": payload}
