"""Principal-owned Google connection domain."""

from .connection import (
    GMAIL_READONLY_SCOPE,
    GOOGLE_IDENTITY_SCOPES,
    GoogleCapability,
    GoogleCapabilityAvailability,
    GoogleConnectionService,
    GoogleConnectionStatus,
    GoogleOAuthTokenState,
)
from .gmail import (
    GmailAPIClient,
    GmailAttachment,
    GmailError,
    GmailMessage,
    GmailSearchResult,
    GmailThread,
)
from .gmail_service import GmailResourceService
from .oauth import GoogleOAuthCoordinator, GoogleOAuthError, GoogleOAuthStart

__all__ = [
    "GMAIL_READONLY_SCOPE",
    "GOOGLE_IDENTITY_SCOPES",
    "GoogleCapability",
    "GoogleCapabilityAvailability",
    "GoogleConnectionService",
    "GoogleConnectionStatus",
    "GoogleOAuthTokenState",
    "GoogleOAuthCoordinator",
    "GoogleOAuthError",
    "GoogleOAuthStart",
    "GmailAPIClient",
    "GmailAttachment",
    "GmailError",
    "GmailMessage",
    "GmailSearchResult",
    "GmailThread",
    "GmailResourceService",
]
