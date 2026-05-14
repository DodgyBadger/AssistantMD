"""Shared memory services and conversation-history abstractions."""

from core.memory.service import (
    ConversationHistoryItem,
    ConversationHistoryProvider,
    ConversationHistoryResult,
    ConversationToolEventItem,
    ConversationToolEventResult,
    InMemoryConversationHistoryProvider,
    MemoryContext,
    MemoryService,
    SQLiteConversationHistoryProvider,
    resolve_conversation_history_provider,
)
from core.memory.workstreams import (
    Workstream,
    WorkstreamArtifact,
    WorkstreamSearchResult,
    WorkstreamStore,
    normalize_field_value,
)

__all__ = [
    "ConversationHistoryItem",
    "ConversationHistoryProvider",
    "ConversationHistoryResult",
    "ConversationToolEventItem",
    "ConversationToolEventResult",
    "InMemoryConversationHistoryProvider",
    "MemoryContext",
    "MemoryService",
    "SQLiteConversationHistoryProvider",
    "Workstream",
    "WorkstreamArtifact",
    "WorkstreamSearchResult",
    "WorkstreamStore",
    "normalize_field_value",
    "resolve_conversation_history_provider",
]
