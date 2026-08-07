"""Authority-mediated access to durable chat sessions."""

from __future__ import annotations

from core.identity import AuthorizationService, require_current_execution_authority

from .chat_store import ChatStore, StoredChatSession


class ChatSessionAccessService:
    """Mediate chat-session discovery and creation under active authority."""

    def __init__(
        self,
        store: ChatStore,
        authorization: AuthorizationService,
    ) -> None:
        self._store = store
        self._authorization = authorization

    def get_session_by_id(self, session_id: str) -> StoredChatSession | None:
        """Return an accessible session, concealing sessions owned by others."""
        authority = require_current_execution_authority()
        session = self._store.get_session_by_id(session_id)
        if session is None:
            return None
        if not self._authorization.can_access_session(authority, session):
            return None
        return session

    def require_session(self, session_id: str) -> StoredChatSession:
        """Return an accessible session or fail with a stable lookup error."""
        session = self.get_session_by_id(session_id)
        if session is None:
            raise LookupError(f"Chat session not found: {session_id}")
        return session

    def list_sessions(self, vault_name: str) -> list[StoredChatSession]:
        """Return sessions in one vault accessible to the active authority."""
        authority = require_current_execution_authority()
        return [
            session
            for session in self._store.list_sessions(vault_name)
            if self._authorization.can_access_session(authority, session)
        ]

    def ensure_session(self, session_id: str, vault_name: str) -> StoredChatSession:
        """Create or touch a session owned by the active authority."""
        authority = require_current_execution_authority()
        existing = self._store.get_session_by_id(session_id)
        if existing is not None and not self._authorization.can_access_session(
            authority, existing
        ):
            # Session reads deliberately conceal resources owned by another
            # principal. Preserve that contract on the create-or-touch path so
            # caller-selected IDs cannot be used as an ownership oracle.
            raise LookupError(f"Chat session not found: {session_id}")
        return self._store.ensure_session(
            session_id=session_id,
            vault_name=vault_name,
            owner_principal_id=authority.principal_id,
        )

    def session_id_exists(self, session_id: str) -> bool:
        """Return whether an identifier is already allocated to any principal."""
        require_current_execution_authority()
        return self._store.get_session_by_id(session_id) is not None
