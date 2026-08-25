"""Principal-owned built-in connection configuration."""

from .availability import ConnectionRequirement, connection_requirement_available
from .models import GmailPreferences, GoogleConnection, GoogleConnectionUpdate
from .service import BuiltInConnectionService

__all__ = [
    "BuiltInConnectionService",
    "ConnectionRequirement",
    "GmailPreferences",
    "GoogleConnection",
    "GoogleConnectionUpdate",
    "connection_requirement_available",
]
