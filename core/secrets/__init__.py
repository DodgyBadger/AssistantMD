"""Principal-owned encrypted secret storage."""

from .bootstrap import (
    SecretsBootstrapState,
    SecretsBootstrapStatus,
    get_encrypted_secrets_service,
    get_secrets_bootstrap_status,
    initialize_secrets_bootstrap,
    require_secrets_ready,
    reset_secrets_bootstrap_status,
)
from .crypto import SecretIntegrityError, SecretKeyring
from .service import EncryptedSecretsService, SecretMetadata, SecretWrite

__all__ = [
    "EncryptedSecretsService",
    "SecretsBootstrapState",
    "SecretsBootstrapStatus",
    "SecretIntegrityError",
    "SecretKeyring",
    "SecretMetadata",
    "SecretWrite",
    "get_secrets_bootstrap_status",
    "get_encrypted_secrets_service",
    "initialize_secrets_bootstrap",
    "require_secrets_ready",
    "reset_secrets_bootstrap_status",
]
