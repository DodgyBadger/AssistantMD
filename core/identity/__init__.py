"""Stable principal and execution-authority contracts."""

from .authorization import (
    AuthorizationError,
    require_execution_task_access,
    require_session_access,
)
from .context import (
    get_current_execution_authority,
    require_current_execution_authority,
    use_execution_authority,
)
from .models import (
    LOCAL_USER_AUTHORITY,
    LOCAL_USER_PRINCIPAL,
    LOCAL_USER_PRINCIPAL_ID,
    SYSTEM_AUTHORITY,
    SYSTEM_PRINCIPAL,
    SYSTEM_PRINCIPAL_ID,
    ExecutionAuthority,
    Principal,
    PrincipalType,
    normalize_principal_id,
)

__all__ = [
    "ExecutionAuthority",
    "AuthorizationError",
    "LOCAL_USER_AUTHORITY",
    "LOCAL_USER_PRINCIPAL",
    "LOCAL_USER_PRINCIPAL_ID",
    "Principal",
    "PrincipalType",
    "SYSTEM_AUTHORITY",
    "SYSTEM_PRINCIPAL",
    "SYSTEM_PRINCIPAL_ID",
    "get_current_execution_authority",
    "normalize_principal_id",
    "require_current_execution_authority",
    "require_execution_task_access",
    "require_session_access",
    "use_execution_authority",
]
