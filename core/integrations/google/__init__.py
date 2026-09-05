"""Principal-owned Google connection domain."""

from .connection import (
    GMAIL_COMPOSE_SCOPE,
    GMAIL_READONLY_SCOPE,
    GOOGLE_IDENTITY_SCOPES,
    GoogleCapability,
    GoogleCapabilityAvailability,
    GoogleConnectionService,
    GoogleConnectionStatus,
    GoogleCredentialChangedError,
    GoogleOAuthClientCredential,
    GoogleOAuthStateChangedError,
    GoogleOAuthTokenState,
)
from .gmail import (
    GmailAPIClient,
    GmailAttachment,
    GmailDraft,
    GmailError,
    GmailMessage,
    GmailSearchResult,
    GmailThread,
)
from .gmail_service import GmailResourceService
from .oauth import GoogleOAuthCoordinator, GoogleOAuthError, GoogleOAuthStart

__all__ = [
    "GMAIL_COMPOSE_SCOPE",
    "GMAIL_READONLY_SCOPE",
    "GOOGLE_IDENTITY_SCOPES",
    "GoogleCapability",
    "GoogleCapabilityAvailability",
    "GoogleConnectionService",
    "GoogleConnectionStatus",
    "GoogleCredentialChangedError",
    "GoogleOAuthClientCredential",
    "GoogleOAuthStateChangedError",
    "GoogleOAuthTokenState",
    "GoogleOAuthCoordinator",
    "GoogleOAuthError",
    "GoogleOAuthStart",
    "GmailAPIClient",
    "GmailAttachment",
    "GmailDraft",
    "GmailError",
    "GmailMessage",
    "GmailSearchResult",
    "GmailThread",
    "GmailResourceService",
]
