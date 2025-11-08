"""
Custom exceptions and error handling for the API module.
"""

from typing import Dict, Optional
from fastapi import HTTPException


class APIException(HTTPException):
    """Base exception for API-related errors."""
    
    def __init__(
        self, 
        status_code: int, 
        error_type: str, 
        message: str, 
        details: Optional[Dict] = None
    ):
        self.error_type = error_type
        self.details = details
        super().__init__(status_code=status_code, detail=message)


class VaultAlreadyExistsError(APIException):
    """Raised when attempting to create a vault that already exists."""
    
    def __init__(self, vault_name: str):
        super().__init__(
            status_code=409,
            error_type="VaultAlreadyExists",
            message=f"Vault '{vault_name}' already exists",
            details={"vault_name": vault_name}
        )


class VaultNotFoundError(APIException):
    """Raised when a requested vault cannot be found."""
    
    def __init__(self, vault_name: str):
        super().__init__(
            status_code=404,
            error_type="VaultNotFound",
            message=f"Vault '{vault_name}' not found",
            details={"vault_name": vault_name}
        )


class InvalidVaultNameError(APIException):
    """Raised when a vault name is invalid for filesystem use."""
    
    def __init__(self, vault_name: str, reason: str):
        super().__init__(
            status_code=400,
            error_type="InvalidVaultName",
            message=f"Invalid vault name '{vault_name}': {reason}",
            details={"vault_name": vault_name, "reason": reason}
        )


class SystemConfigurationError(APIException):
    """Raised when there are system configuration issues."""
    
    def __init__(self, message: str, details: Optional[Dict] = None):
        super().__init__(
            status_code=500,
            error_type="SystemConfiguration",
            message=f"System configuration error: {message}",
            details=details
        )


class SchedulerError(APIException):
    """Raised when scheduler operations fail."""
    
    def __init__(self, message: str, details: Optional[Dict] = None):
        super().__init__(
            status_code=500,
            error_type="SchedulerError",
            message=f"Scheduler error: {message}",
            details=details
        )


class FileSystemError(APIException):
    """Raised when file system operations fail."""
    
    def __init__(self, message: str, details: Optional[Dict] = None):
        super().__init__(
            status_code=500,
            error_type="FileSystemError",
            message=f"File system error: {message}",
            details=details
        )