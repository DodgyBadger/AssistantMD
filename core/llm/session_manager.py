"""
Session management for chat conversation history.

Stores Pydantic AI ModelMessage objects for stateful chat execution.
"""

from typing import Optional
from pydantic_ai.messages import ModelMessage


class SessionManager:
    """
    Manages conversation history for chat sessions.

    Sessions are keyed by: {session_id}
    Session ID format: {vault_name}_{timestamp} (e.g., ProjectVault_20251002_143022)
    This embeds vault context in the session ID itself.
    """

    def __init__(self):
        self._sessions: dict[str, list[ModelMessage]] = {}

    def get_history(
        self,
        session_id: str,
        vault_name: str  # Kept for backward compatibility, not used
    ) -> Optional[list[ModelMessage]]:
        """
        Get conversation history for session.

        Returns None if no history exists (first message in conversation).
        """
        return self._sessions.get(session_id)

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
        if session_id not in self._sessions:
            self._sessions[session_id] = []
        self._sessions[session_id].extend(messages)

    def clear_history(self, session_id: str, vault_name: str):
        """Clear conversation history for specific session."""
        if session_id in self._sessions:
            del self._sessions[session_id]

    def get_message_count(self, session_id: str, vault_name: str) -> int:
        """Get count of messages in session."""
        history = self.get_history(session_id, vault_name)
        return len(history) if history else 0

    def compact_session(
        self,
        session_id: str,
        vault_name: str,
        summary_message: ModelMessage
    ):
        """
        Replace session history with a single summary message.

        Used to preserve context while reducing token count.
        """
        self._sessions[session_id] = [summary_message]
