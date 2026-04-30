"""Compatibility re-exports for older conversation-history provider imports."""

from core.memory.service import (
    ConversationHistoryItem,
    ConversationHistoryProvider,
    ConversationHistoryResult,
    ConversationToolEventItem,
    ConversationToolEventResult,
    InMemoryConversationHistoryProvider,
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
    "SQLiteConversationHistoryProvider",
    "resolve_conversation_history_provider",
]
