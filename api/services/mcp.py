"""Thin API projections for principal-owned MCP connection management."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict

from core.identity import require_current_execution_authority
from core.logger import UnifiedLogger
from core.mcp import (
    MCPAuthMode,
    MCPConnection,
    MCPConnectionCreate,
    MCPConnectionService,
    MCPConnectionUpdate,
    MCPTransport,
)
from core.runtime.state import get_runtime_context

from ..exceptions import APIException
from ..models import (
    MCPConnectionCreateRequest,
    MCPConnectionInfo,
    MCPConnectionTestResponse,
    MCPConnectionUpdateRequest,
    MCPCredentialUpdateRequest,
    OperationResult,
)

logger = UnifiedLogger(tag="mcp-connections")


def list_mcp_connections() -> list[MCPConnectionInfo]:
    """List sanitized connections for request authority."""
    return [_to_info(item) for item in _service().list_connections()]


def create_mcp_connection(
    request: MCPConnectionCreateRequest,
) -> MCPConnectionInfo:
    """Create a connection without accepting an owner override."""
    with _domain_errors():
        connection = _service().create_connection(
            MCPConnectionCreate(
                display_name=request.display_name,
                url=request.url,
                transport=MCPTransport(request.transport),
                auth_mode=MCPAuthMode(request.auth_mode),
                header_name=request.header_name,
                enabled=request.enabled,
                allowed_tools=(
                    tuple(request.allowed_tools)
                    if request.allowed_tools is not None
                    else None
                ),
                credential=(
                    request.credential.get_secret_value()
                    if request.credential is not None
                    else None
                ),
            )
        )
    _log_change("mcp_connection_created", connection)
    return _to_info(connection)


def update_mcp_connection(
    connection_id: str, request: MCPConnectionUpdateRequest
) -> MCPConnectionInfo:
    """Replace mutable connection metadata under request authority."""
    with _domain_errors():
        connection = _service().update_connection(
            connection_id,
            MCPConnectionUpdate(
                display_name=request.display_name,
                url=request.url,
                transport=MCPTransport(request.transport),
                auth_mode=MCPAuthMode(request.auth_mode),
                header_name=request.header_name,
                enabled=request.enabled,
                allowed_tools=(
                    tuple(request.allowed_tools)
                    if request.allowed_tools is not None
                    else None
                ),
            ),
        )
    _log_change("mcp_connection_updated", connection)
    return _to_info(connection)


def set_mcp_credential(
    connection_id: str, request: MCPCredentialUpdateRequest
) -> MCPConnectionInfo:
    """Set a static credential without returning its value."""
    with _domain_errors():
        connection = _service().set_credential(
            connection_id,
            request.credential.get_secret_value(),
        )
    _log_change("mcp_credential_updated", connection)
    return _to_info(connection)


def clear_mcp_credential(connection_id: str) -> MCPConnectionInfo:
    """Clear a static credential under request authority."""
    with _domain_errors():
        connection = _service().clear_credential(connection_id)
    _log_change("mcp_credential_cleared", connection)
    return _to_info(connection)


def delete_mcp_connection(connection_id: str) -> OperationResult:
    """Delete connection metadata and associated static credential."""
    with _domain_errors():
        _service().delete_connection(connection_id)
    logger.info(
        "MCP connection deleted",
        data={"event": "mcp_connection_deleted", "connection_id": connection_id},
    )
    return OperationResult(
        success=True,
        message="Deleted MCP connection.",
        restart_required=False,
    )


async def test_mcp_connection(connection_id: str) -> MCPConnectionTestResponse:
    """Test managed initialization and return sanitized tool discovery."""
    with _domain_errors():
        connection = _service().get_connection(connection_id)
        if connection is None:
            raise LookupError("MCP connection not found.")
        runtime = get_runtime_context()
        if runtime.mcp_manager is None:
            raise APIException(
                status_code=503,
                error_type="MCPRuntimeUnavailable",
                message="MCP runtime connections are unavailable.",
            )
        result = await runtime.mcp_manager.test_connection(
            require_current_execution_authority(),
            connection,
        )
    return MCPConnectionTestResponse(**asdict(result))


def _service() -> MCPConnectionService:
    service = get_runtime_context().mcp_connections
    if service is None:
        raise APIException(
            status_code=503,
            error_type="SecretsLocked",
            message="MCP configuration is unavailable while encrypted secrets are locked.",
        )
    return service


def _to_info(connection: MCPConnection) -> MCPConnectionInfo:
    payload = asdict(connection)
    allowed_tools = payload.get("allowed_tools")
    payload["allowed_tools"] = (
        list(allowed_tools) if allowed_tools is not None else None
    )
    return MCPConnectionInfo.model_validate(payload)


def _log_change(event: str, connection: MCPConnection) -> None:
    logger.info(
        "MCP connection configuration changed",
        data={
            "event": event,
            "connection_id": connection.connection_id,
            "slug": connection.slug,
            "enabled": connection.enabled,
            "auth_mode": connection.auth_mode.value,
            "credential_present": connection.credential_present,
            "config_version": connection.config_version,
        },
    )


@contextmanager
def _domain_errors() -> Iterator[None]:
    try:
        yield
    except LookupError as exc:
        raise APIException(
            status_code=404,
            error_type="MCPConnectionNotFound",
            message="MCP connection not found.",
        ) from exc
    except ValueError as exc:
        raise APIException(
            status_code=400,
            error_type="InvalidMCPConnection",
            message=str(exc),
        ) from exc
