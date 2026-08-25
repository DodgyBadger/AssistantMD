"""Typed built-in connection configuration models."""

from __future__ import annotations

from dataclasses import dataclass, field

GMAIL_SEARCH_DEFAULT_RESULTS = 20
GMAIL_SEARCH_MAX_RESULTS = 100
GMAIL_SEARCH_RESULTS_CEILING = 500
GMAIL_MESSAGE_MAX_CHARACTERS = 50_000
GMAIL_MESSAGE_CHARACTERS_CEILING = 250_000
GMAIL_THREAD_MAX_MESSAGES = 25
GMAIL_THREAD_MESSAGES_CEILING = 100


@dataclass(frozen=True)
class GmailPreferences:
    """Principal-owned Gmail capability limits."""

    search_default_results: int = GMAIL_SEARCH_DEFAULT_RESULTS
    search_max_results: int = GMAIL_SEARCH_MAX_RESULTS
    message_max_characters: int = GMAIL_MESSAGE_MAX_CHARACTERS
    thread_max_messages: int = GMAIL_THREAD_MAX_MESSAGES

    def __post_init__(self) -> None:
        if not 1 <= self.search_default_results <= GMAIL_SEARCH_RESULTS_CEILING:
            raise ValueError("Gmail default search results must be between 1 and 500.")
        if not 1 <= self.search_max_results <= GMAIL_SEARCH_RESULTS_CEILING:
            raise ValueError("Gmail maximum search results must be between 1 and 500.")
        if self.search_default_results > self.search_max_results:
            raise ValueError(
                "Gmail default search results cannot exceed the configured maximum."
            )
        if not 1 <= self.message_max_characters <= GMAIL_MESSAGE_CHARACTERS_CEILING:
            raise ValueError("Gmail message characters must be between 1 and 250000.")
        if not 1 <= self.thread_max_messages <= GMAIL_THREAD_MESSAGES_CEILING:
            raise ValueError("Gmail thread messages must be between 1 and 100.")


@dataclass(frozen=True)
class GoogleConnectionUpdate:
    """Mutable non-secret Google connection configuration."""

    client_id: str
    gmail: GmailPreferences = field(default_factory=GmailPreferences)

    def __post_init__(self) -> None:
        clean_client_id = str(self.client_id or "").strip()
        if not clean_client_id:
            raise ValueError("Google OAuth client ID cannot be empty.")
        if len(clean_client_id) > 2048:
            raise ValueError("Google OAuth client ID is too long.")
        object.__setattr__(self, "client_id", clean_client_id)


@dataclass(frozen=True)
class GoogleConnection:
    """Sanitized principal-owned Google connection metadata."""

    client_id: str
    gmail: GmailPreferences
    config_version: int
    created_at: str
    updated_at: str
