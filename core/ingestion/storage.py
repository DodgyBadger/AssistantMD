"""
Storage helpers for writing rendered artifacts to vaults.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List

from core.constants import ASSISTANTMD_ROOT_DIR, IMPORT_COLLECTION_DIR
from core.ingestion.models import RenderOptions
from core.runtime.paths import get_data_root


def default_storage(rendered: List[Dict], options: RenderOptions) -> List[str]:
    """
    Write rendered artifacts to disk and return written paths (vault-relative).
    """
    if not options.vault:
        raise ValueError("RenderOptions.vault is required for storage")

    data_root = Path(get_data_root())
    vault_root = data_root / options.vault
    outputs: List[str] = []

    for artifact in rendered:
        rel_path = artifact["path"]
        full_path = vault_root / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        content = artifact["content"]
        full_path.write_text(content, encoding="utf-8")
        outputs.append(str(full_path))

    # Clean up source file after successful write to avoid clutter in vaults
    if options.source_filename:
        try:
            source_path = Path(options.source_filename).resolve()
            # Only delete files under the current vault to avoid unintended removals
            if str(source_path).startswith(str(vault_root.resolve())) and source_path.is_file():
                source_path.unlink(missing_ok=True)
        except Exception:
            # Swallow cleanup errors; ingestion output already written
            pass

    return outputs
