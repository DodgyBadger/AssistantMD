"""Shared memory services and conversation-history abstractions."""

from core.memory.experiment_harness import MemoryExperimentFixture, MemoryExperimentHarness
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
    CandidateField,
    RelatedWorkstreamCandidate,
    Workstream,
    WorkstreamArtifact,
    WorkstreamField,
    WorkstreamStore,
    extract_candidate_fields,
    normalize_field_value,
)

__all__ = [
    "CandidateField",
    "ConversationHistoryItem",
    "ConversationHistoryProvider",
    "ConversationHistoryResult",
    "ConversationToolEventItem",
    "ConversationToolEventResult",
    "InMemoryConversationHistoryProvider",
    "MemoryExperimentFixture",
    "MemoryExperimentHarness",
    "MemoryContext",
    "MemoryService",
    "RelatedWorkstreamCandidate",
    "SQLiteConversationHistoryProvider",
    "Workstream",
    "WorkstreamArtifact",
    "WorkstreamField",
    "WorkstreamStore",
    "extract_candidate_fields",
    "normalize_field_value",
    "resolve_conversation_history_provider",
]
