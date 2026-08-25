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
]
