"""Principal-owned built-in connection configuration."""

from .models import GmailPreferences, GoogleConnection, GoogleConnectionUpdate
from .service import BuiltInConnectionService

__all__ = [
    "BuiltInConnectionService",
    "GmailPreferences",
    "GoogleConnection",
    "GoogleConnectionUpdate",
]
