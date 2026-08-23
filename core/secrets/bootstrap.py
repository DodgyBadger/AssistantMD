"""Bootstrap readiness state for encrypted secret storage."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .crypto import SecretIntegrityError, SecretKeyring
from .service import EncryptedSecretsService


class SecretsBootstrapState(StrEnum):
    """Process-level encrypted-secrets readiness."""

    READY = "ready"
    LOCKED = "locked"


@dataclass(frozen=True)
class SecretsBootstrapStatus:
    """Sanitized encrypted-secrets startup status."""

    state: SecretsBootstrapState
    reason: str | None = None

    @property
    def ready(self) -> bool:
        """Return whether encrypted secret operations may proceed."""
        return self.state is SecretsBootstrapState.READY


_status: SecretsBootstrapStatus | None = None
_service: EncryptedSecretsService | None = None


def initialize_secrets_bootstrap(system_root: str | Path) -> SecretsBootstrapStatus:
    """Inspect key configuration and existing records without unsafe fallback."""
    global _service, _status
    try:
        keyring = SecretKeyring.from_environment()
        service = EncryptedSecretsService(
            system_root=str(Path(system_root)), keyring=keyring
        )
        service.verify_all()
    except (RuntimeError, ValueError, sqlite3.DatabaseError) as exc:
        _service = None
        _status = SecretsBootstrapStatus(
            state=SecretsBootstrapState.LOCKED,
            reason=str(exc),
        )
    else:
        _service = service
        _status = SecretsBootstrapStatus(state=SecretsBootstrapState.READY)
    return _status


def get_secrets_bootstrap_status() -> SecretsBootstrapStatus | None:
    """Return startup status, or None before runtime bootstrap inspects it."""
    return _status


def require_secrets_ready() -> None:
    """Block model/secret execution when runtime bootstrap locked secrets."""
    status = _status
    if status is not None and not status.ready:
        raise SecretIntegrityError(
            "Encrypted secrets are locked. Restore or configure the installation "
            "key in .env, then restart AssistantMD."
        )


def get_encrypted_secrets_service() -> EncryptedSecretsService:
    """Return the initialized service or fail with the locked-state contract."""
    require_secrets_ready()
    if _service is None:
        raise SecretIntegrityError(
            "Encrypted secrets are unavailable before runtime bootstrap completes."
        )
    return _service


def reset_secrets_bootstrap_status() -> None:
    """Reset process state for isolated tests and runtime teardown."""
    global _service, _status
    _status = None
    _service = None
