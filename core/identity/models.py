"""Principal identity values independent of transport and persistence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

LOCAL_USER_PRINCIPAL_ID = "local-user"
SYSTEM_PRINCIPAL_ID = "system"


class PrincipalType(StrEnum):
    """Stable categories of actors that can authorize work."""

    USER = "user"
    SYSTEM = "system"


def normalize_principal_id(value: str) -> str:
    """Return a validated stable principal identifier."""
    normalized = value.strip()
    if not normalized:
        raise ValueError("Principal ID cannot be empty.")
    if len(normalized) > 128:
        raise ValueError("Principal ID cannot exceed 128 characters.")
    if any(character.isspace() for character in normalized):
        raise ValueError("Principal ID cannot contain whitespace.")
    return normalized


@dataclass(frozen=True)
class Principal:
    """One stable internal actor identity."""

    principal_id: str
    principal_type: PrincipalType
    roles: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "principal_id",
            normalize_principal_id(self.principal_id),
        )


@dataclass(frozen=True)
class ExecutionAuthority:
    """Principal identity captured for one execution boundary."""

    principal_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "principal_id",
            normalize_principal_id(self.principal_id),
        )

    @classmethod
    def from_principal(cls, principal: Principal) -> ExecutionAuthority:
        """Create execution authority for a resolved principal."""
        return cls(principal_id=principal.principal_id)


LOCAL_USER_PRINCIPAL = Principal(
    principal_id=LOCAL_USER_PRINCIPAL_ID,
    principal_type=PrincipalType.USER,
    roles=frozenset({"admin"}),
)
SYSTEM_PRINCIPAL = Principal(
    principal_id=SYSTEM_PRINCIPAL_ID,
    principal_type=PrincipalType.SYSTEM,
)
LOCAL_USER_AUTHORITY = ExecutionAuthority.from_principal(LOCAL_USER_PRINCIPAL)
SYSTEM_AUTHORITY = ExecutionAuthority.from_principal(SYSTEM_PRINCIPAL)
