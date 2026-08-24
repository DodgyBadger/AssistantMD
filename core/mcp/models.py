"""Typed contracts for principal-owned MCP connections."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MCPTransport(StrEnum):
    """Remote transports supported by the initial MCP integration."""

    STREAMABLE_HTTP = "streamable_http"
    SSE = "sse"


class MCPAuthMode(StrEnum):
    """Credential modes stored independently from connection metadata."""

    NONE = "none"
    BEARER = "bearer"
    HEADER = "header"
    OAUTH = "oauth"


@dataclass(frozen=True)
class MCPConnection:
    """Sanitized connection definition visible to its owning principal."""

    connection_id: str
    slug: str
    display_name: str
    url: str
    transport: MCPTransport
    auth_mode: MCPAuthMode
    header_name: str | None
    enabled: bool
    allowed_tools: tuple[str, ...] | None
    credential_present: bool
    config_version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class MCPConnectionCreate:
    """User-controlled fields accepted when creating a connection."""

    display_name: str
    url: str
    transport: MCPTransport = MCPTransport.STREAMABLE_HTTP
    auth_mode: MCPAuthMode = MCPAuthMode.NONE
    header_name: str | None = None
    enabled: bool = True
    allowed_tools: tuple[str, ...] | None = None
    credential: str | None = None


@dataclass(frozen=True)
class MCPConnectionUpdate:
    """Mutable connection fields; identity and ownership are intentionally absent."""

    display_name: str
    url: str
    transport: MCPTransport
    auth_mode: MCPAuthMode
    header_name: str | None
    enabled: bool
    allowed_tools: tuple[str, ...] | None


@dataclass(frozen=True)
class MCPConnectionTestResult:
    """Sanitized connection-test response independent of transport errors."""

    status: str
    ready: bool
    tool_count: int | None
    tool_names: tuple[str, ...]
    message: str
