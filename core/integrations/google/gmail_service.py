"""Principal-authorized Gmail resources shared by tools and future ingestion."""

from __future__ import annotations

from collections.abc import Callable

from core.connections import BuiltInConnectionService, GmailPreferences
from core.identity import ExecutionAuthority

from .connection import GoogleCapability, GoogleConnectionService
from .gmail import GmailAPIClient, GmailMessage, GmailSearchResult, GmailThread
from .oauth import GoogleOAuthCoordinator


class GmailResourceService:
    """Authorize and apply principal preferences before Gmail resource access."""

    def __init__(
        self,
        *,
        connections: BuiltInConnectionService,
        google: GoogleConnectionService,
        oauth: GoogleOAuthCoordinator,
        client_factory: Callable[[ExecutionAuthority], GmailAPIClient] | None = None,
    ) -> None:
        self._connections = connections
        self._google = google
        self._oauth = oauth
        self._client_factory = client_factory

    def status(self, authority: ExecutionAuthority) -> dict[str, object]:
        """Return sanitized Gmail account and capability readiness."""
        status = self._google.status(authority)
        availability = self._google.capability_availability(
            authority, GoogleCapability.GMAIL_READ
        )
        return {
            "provider": "google",
            "capability": GoogleCapability.GMAIL_READ.value,
            "available": availability.available,
            "connection_state": availability.connection_state,
            "account_email": status.account_email,
            "missing_scopes": list(availability.missing_scopes),
        }

    async def search(
        self,
        authority: ExecutionAuthority,
        *,
        query: str,
        max_results: int | None = None,
    ) -> tuple[GmailSearchResult, bool]:
        """Search under principal configuration and report request capping."""
        preferences = self._preferences(authority)
        requested = max_results or preferences.search_default_results
        effective = min(requested, preferences.search_max_results)
        return (
            await self._client(authority).search(query=query, max_results=effective),
            requested > effective,
        )

    async def get_message(
        self, authority: ExecutionAuthority, message_id: str
    ) -> GmailMessage:
        preferences = self._preferences(authority)
        return await self._client(authority).get_message(
            message_id, max_characters=preferences.message_max_characters
        )

    async def get_thread(
        self, authority: ExecutionAuthority, thread_id: str
    ) -> GmailThread:
        preferences = self._preferences(authority)
        return await self._client(authority).get_thread(
            thread_id,
            max_messages=preferences.thread_max_messages,
            max_characters=preferences.message_max_characters,
        )

    def _preferences(self, authority: ExecutionAuthority) -> GmailPreferences:
        availability = self._google.capability_availability(
            authority, GoogleCapability.GMAIL_READ
        )
        if not availability.available:
            raise ValueError(
                "Gmail connection is unavailable. Reconnect Google with Gmail read access."
            )
        connection = self._connections.get_google_connection_for_authority(authority)
        if connection is None:
            raise ValueError("Google connection is not configured.")
        return connection.gmail

    def _client(self, authority: ExecutionAuthority) -> GmailAPIClient:
        if self._client_factory is not None:
            return self._client_factory(authority)
        return GmailAPIClient(
            access_token_provider=lambda: self._oauth.access_token(authority)
        )
