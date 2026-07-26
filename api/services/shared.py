"""State shared by API service modules."""

from typing import Any

from core.logger import UnifiedLogger
from core.runtime.state import get_runtime_context

logger = UnifiedLogger(tag="api-services")


def get_workflow_loader() -> Any:
    """Return the runtime-owned workflow loader."""
    return get_runtime_context().workflow_loader


def get_vault_path(vault_name: str) -> str:
    """Return one configured vault path from the runtime loader cache."""
    vault_info = get_workflow_loader().get_vault_info()
    if vault_name not in vault_info:
        raise ValueError(f"Vault '{vault_name}' not found")
    path = vault_info[vault_name].get("path")
    if not isinstance(path, str) or not path:
        raise ValueError(f"Vault '{vault_name}' has no configured path")
    return path
