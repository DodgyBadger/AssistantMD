"""
Session management for chat conversation history.

Stores Pydantic AI ModelMessage objects in durable SQLite-backed session storage.
"""

from typing import Optional
from typing import Callable
from pydantic_ai.messages import ModelMessage

from core.chat import ChatStore


class SessionManager:
    """
    Manages conversation history for chat sessions.

    Sessions are keyed by: {session_id}
    Session ID format: {vault_name}_{timestamp} (e.g., ProjectVault_20251002_143022)
    This embeds vault context in the session ID itself.
    """

    def __init__(self):
        self._store = ChatStore()

    def get_history(
        self,
        session_id: str,
        vault_name: str  # Kept for backward compatibility, not used
    ) -> Optional[list[ModelMessage]]:
        """
        Get conversation history for session.

        Returns None if no history exists (first message in conversation).
        """
        return self._store.get_history(session_id, vault_name)

    def get_recent(
        self,
        session_id: str,
        vault_name: str,  # Kept for backward compatibility, not used
        limit: int
    ) -> list[ModelMessage]:
        """
        Get the last N messages for a session.

        Returns an empty list if no history exists or limit <= 0.
        Always returns a new list (safe to mutate).
        """
        return self._store.get_recent(session_id, vault_name, limit)

    def get_recent_matching(
        self,
        session_id: str,
        vault_name: str,  # Kept for backward compatibility, not used
        limit: int,
        predicate: Callable[[ModelMessage], bool],
    ) -> list[ModelMessage]:
        """
        Get up to N most recent messages matching a predicate.

        Iterates from the end and stops once limit matches are found.
        Returns in chronological order (oldest to newest of the matched set).
        """
        return self._store.get_recent_matching(session_id, vault_name, limit, predicate)

    def add_messages(
        self,
        session_id: str,
        vault_name: str,  # Kept for backward compatibility, not used
        messages: list[ModelMessage]
    ):
        """
        Add new messages to session history.

        Messages should come from result.new_messages() after agent run.
        """
        self._store.add_messages(session_id, vault_name, messages)

    def clear_history(self, session_id: str, vault_name: str):
        """Clear conversation history for specific session."""
        self._store.clear_history(session_id, vault_name)

    def get_message_count(self, session_id: str, vault_name: str) -> int:
        """Get count of messages in session."""
        return self._store.get_message_count(session_id, vault_name)
