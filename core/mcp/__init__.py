"""Principal-owned MCP connection domain."""

from .models import (
    MCPAuthMode,
    MCPConnection,
    MCPConnectionCreate,
    MCPConnectionTestResult,
    MCPConnectionUpdate,
    MCPTransport,
)
from .service import MCPConnectionService

__all__ = [
    "MCPAuthMode",
    "MCPConnection",
    "MCPConnectionCreate",
    "MCPConnectionLease",
    "MCPConnectionManager",
    "MCPConnectionService",
    "MCPConnectionTestResult",
    "MCPConnectionUpdate",
    "MCPReadinessSnapshot",
    "MCPTransport",
    "MCPUnavailableConnection",
]
from .manager import (
    MCPConnectionLease,
    MCPConnectionManager,
    MCPReadinessSnapshot,
    MCPUnavailableConnection,
)
