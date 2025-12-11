"""
Storage helpers for writing rendered artifacts to vaults.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List

from core.constants import ASSISTANTMD_ROOT_DIR
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
        raw_rel_path = Path(artifact["path"])
        # Normalize away any stray "." segments to keep vault-relative paths clean
        rel_path = Path(*[part for part in raw_rel_path.parts if part not in ("", ".")])
        full_path = vault_root / rel_path
        if full_path.exists():
            stem = full_path.stem
            suffix = full_path.suffix
            counter = 1
            while True:
                candidate = full_path.with_name(f"{stem}_{counter}{suffix}")
                if not candidate.exists():
                    full_path = candidate
                    rel_path = Path(*candidate.relative_to(vault_root).parts)
                    break
                counter += 1
        full_path.parent.mkdir(parents=True, exist_ok=True)
        content = artifact["content"]
        full_path.write_text(content, encoding="utf-8")
        # Return vault-relative path for API/status reporting
        outputs.append(rel_path.as_posix())

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
