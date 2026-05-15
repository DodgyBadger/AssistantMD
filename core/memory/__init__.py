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
from core.memory.session_memory import (
    RelatedSessionContribution,
    RelatedSessionResult,
    SessionMemory,
    SessionMemoryArtifact,
    SessionMemorySearchResult,
    SessionMemoryStore,
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
    "RelatedSessionContribution",
    "RelatedSessionResult",
    "SQLiteConversationHistoryProvider",
    "SessionMemory",
    "SessionMemoryArtifact",
    "SessionMemorySearchResult",
    "SessionMemoryStore",
    "normalize_field_value",
    "resolve_conversation_history_provider",
]
