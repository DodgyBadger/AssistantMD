"""Interactive request principal resolution."""

from core.identity import LOCAL_USER_PRINCIPAL, Principal


def resolve_request_principal() -> Principal:
    """Resolve the fixed interactive principal for the single-user product."""
    return LOCAL_USER_PRINCIPAL
