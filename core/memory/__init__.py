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
from core.memory.work_episodes import (
    CandidateField,
    RelatedEpisodeCandidate,
    WorkEpisode,
    WorkEpisodeArtifact,
    WorkEpisodeField,
    WorkEpisodeStore,
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
    "RelatedEpisodeCandidate",
    "SQLiteConversationHistoryProvider",
    "WorkEpisode",
    "WorkEpisodeArtifact",
    "WorkEpisodeField",
    "WorkEpisodeStore",
    "extract_candidate_fields",
    "normalize_field_value",
    "resolve_conversation_history_provider",
]
