"""Outbound network policy for user-configured MCP servers."""

from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

MCP_INSECURE_HTTP_ENV = "ASSISTANTMD_MCP_ALLOW_INSECURE_HTTP"


class MCPNetworkPolicyError(ValueError):
    """Raised when an MCP endpoint violates outbound network policy."""


@dataclass(frozen=True)
class MCPResolvedEndpoint:
    """Validated endpoint information retained for diagnostics and tests."""

    hostname: str
    addresses: tuple[str, ...]
    secure: bool


def insecure_http_allowed_from_environment() -> bool:
    """Return whether explicit local-development HTTP access is enabled."""
    return os.getenv(MCP_INSECURE_HTTP_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


async def validate_mcp_endpoint(
    url: str,
    *,
    allow_insecure_http: bool,
) -> MCPResolvedEndpoint:
    """Resolve and validate an MCP URL immediately before connecting."""
    parsed = urlsplit(str(url or "").strip())
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise MCPNetworkPolicyError("MCP servers must use HTTP or HTTPS.")
    if parsed.username or parsed.password:
        raise MCPNetworkPolicyError("MCP server URLs cannot contain credentials.")
    hostname = parsed.hostname
    if not hostname:
        raise MCPNetworkPolicyError("MCP server URL must include a hostname.")

    try:
        addresses = await asyncio.to_thread(_resolve_addresses, hostname)
    except OSError as exc:
        raise MCPNetworkPolicyError(
            "MCP server hostname could not be resolved."
        ) from exc
    if not addresses:
        raise MCPNetworkPolicyError("MCP server hostname could not be resolved.")

    parsed_addresses = tuple(ipaddress.ip_address(address) for address in addresses)
    if any(_is_forbidden_address(address) for address in parsed_addresses):
        raise MCPNetworkPolicyError("MCP server resolved to a prohibited address.")

    has_local = any(_is_local_address(address) for address in parsed_addresses)
    has_public = any(address.is_global for address in parsed_addresses)
    if has_local and has_public:
        raise MCPNetworkPolicyError(
            "MCP server hostname resolved to mixed public and local addresses."
        )
    if scheme == "http" and (not allow_insecure_http or has_public):
        raise MCPNetworkPolicyError(
            "Plain HTTP MCP connections require the explicit local-development allowance."
        )

    return MCPResolvedEndpoint(
        hostname=hostname,
        addresses=tuple(str(address) for address in parsed_addresses),
        secure=scheme == "https",
    )


def _resolve_addresses(hostname: str) -> tuple[str, ...]:
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        return tuple(dict.fromkeys(str(info[4][0]) for info in infos))
    return (str(literal),)


def _is_local_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return address.is_private or address.is_loopback


def _is_forbidden_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    return (
        address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    )
