"""
Utility functions for API operations.
"""

import os
import re
import traceback
from datetime import datetime
from fastapi.responses import JSONResponse

from .models import ErrorResponse
from .exceptions import APIException, InvalidVaultNameError
from core.logger import UnifiedLogger
from core.settings.store import get_general_settings

# Create API logger
logger = UnifiedLogger(tag="api")


def generate_session_id(vault_name: str) -> str:
    """
    Generate meaningful session ID from vault and timestamp.

    Format: {vault_name}_{YYYYMMDD_HHMMSS}
    Example: MyVault_20251002_143022

    Args:
        vault_name: Vault name to include in session ID

    Returns:
        Session ID string with format {vault_name}_{timestamp}
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Sanitize vault name for filesystem safety
    safe_vault_name = vault_name.replace(" ", "_").replace("/", "_")
    return f"{safe_vault_name}_{timestamp}"


def validate_vault_name(vault_name: str) -> str:
    """
    Validate and clean a vault name for filesystem safety.
    
    Args:
        vault_name: Raw vault name from user input
        
    Returns:
        Cleaned vault name safe for filesystem use
        
    Raises:
        InvalidVaultNameError: If vault name is invalid
    """
    if not vault_name or not vault_name.strip():
        raise InvalidVaultNameError(vault_name, "Vault name cannot be empty")
    
    # Clean the name
    cleaned = vault_name.strip()
    
    # Check length
    if len(cleaned) > 100:
        raise InvalidVaultNameError(vault_name, "Vault name too long (max 100 characters)")
    
    if len(cleaned) < 1:
        raise InvalidVaultNameError(vault_name, "Vault name too short")
    
    # Check for invalid characters (allow alphanumeric, hyphens, underscores, spaces)
    if not re.match(r'^[a-zA-Z0-9\-_\s]+$', cleaned):
        raise InvalidVaultNameError(
            vault_name, 
            "Vault name contains invalid characters. Only letters, numbers, hyphens, underscores, and spaces are allowed"
        )
    
    # Check for reserved names
    reserved_names = {'con', 'prn', 'aux', 'nul', 'logs', 'system'}
    if cleaned.lower() in reserved_names:
        raise InvalidVaultNameError(vault_name, f"'{cleaned}' is a reserved name")
    
    # Check that it doesn't start or end with spaces or special chars
    if cleaned != cleaned.strip():
        raise InvalidVaultNameError(vault_name, "Vault name cannot start or end with spaces")
    
    # Replace spaces with hyphens for filesystem safety
    filesystem_safe = re.sub(r'\s+', '-', cleaned)
    
    return filesystem_safe


def create_error_response(exception: Exception) -> JSONResponse:
    """
    Create a standardized error response from an exception.
    
    Args:
        exception: The exception that occurred
        
    Returns:
        JSONResponse with standardized error format
    """
    if isinstance(exception, APIException):
        error_response = ErrorResponse(
            error=exception.error_type,
            message=exception.detail,
            details=exception.details
        )
        return JSONResponse(
            status_code=exception.status_code,
            content=error_response.model_dump()
        )
    else:
        # Handle unexpected exceptions
        # Include detailed traceback in development/debug mode
        settings = get_general_settings()
        debug_setting = settings.get("debug")
        debug_mode = bool(debug_setting and getattr(debug_setting, "value", False))
        
        if debug_mode:
            # Include full traceback for debugging
            full_traceback = traceback.format_exc()
            error_response = ErrorResponse(
                error="InternalServerError",
                message=str(exception),
                details={
                    "error_type": type(exception).__name__,
                    "traceback": full_traceback
                }
            )
        else:
            # Generic error for production
            error_response = ErrorResponse(
                error="InternalServerError", 
                message="An unexpected error occurred",
                details={"error_type": type(exception).__name__}
            )
        
        # Always log the full traceback server-side
        logger.error(f"Unexpected API error: {traceback.format_exc()}")
        
        return JSONResponse(
            status_code=500,
            content=error_response.model_dump()
        )


def safe_path_join(*paths) -> str:
    """
    Safely join paths and ensure the result is within expected bounds.
    
    Args:
        *paths: Path components to join
        
    Returns:
        Safely joined path
        
    Raises:
        ValueError: If path traversal is detected
    """
    joined = os.path.join(*paths)
    
    # Normalize the path to resolve any .. or . components
    normalized = os.path.normpath(joined)
    
    # Check for path traversal attempts
    if '..' in normalized or normalized.startswith('/'):
        if not normalized.startswith('/app/data'):
            raise ValueError(f"Path traversal detected or invalid path: {normalized}")
    
    return normalized
