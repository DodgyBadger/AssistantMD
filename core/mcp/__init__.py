"""Principal-owned MCP connection domain."""

from .models import (
    MCPAuthMode,
    MCPConnection,
    MCPConnectionCreate,
    MCPConnectionTestResult,
    MCPConnectionUpdate,
    MCPTransport,
)
from .oauth_storage import ConnectedMCPOAuth, EncryptedMCPOAuthStorage
from .service import MCPConnectionService, MCPMutationUnavailableError

__all__ = [
    "ConnectedMCPOAuth",
    "MCPAuthMode",
    "MCPConnection",
    "MCPConnectionCreate",
    "MCPConnectionLease",
    "MCPConnectionManager",
    "MCPConnectionService",
    "MCPMutationUnavailableError",
    "MCPConnectionTestResult",
    "MCPConnectionUpdate",
    "MCPReadinessSnapshot",
    "MCPTransport",
    "MCPUnavailableConnection",
    "EncryptedMCPOAuthStorage",
]
from .manager import (
    MCPConnectionLease,
    MCPConnectionManager,
    MCPReadinessSnapshot,
    MCPUnavailableConnection,
)
