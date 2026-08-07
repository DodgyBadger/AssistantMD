"""Interactive request principal resolution and request-scope installation."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends

from core.identity import (
    LOCAL_USER_PRINCIPAL,
    ExecutionAuthority,
    Principal,
    use_execution_authority,
)


def resolve_request_principal() -> Principal:
    """Resolve the fixed interactive principal for the single-user product."""
    return LOCAL_USER_PRINCIPAL


async def use_request_authority(
    principal: Principal = Depends(resolve_request_principal),
) -> AsyncIterator[ExecutionAuthority]:
    """Install resolved authority for the complete interactive request scope."""
    authority = ExecutionAuthority.from_principal(principal)
    with use_execution_authority(authority):
        yield authority
