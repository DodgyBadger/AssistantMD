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
    "resolve_conversation_history_provider",
]
