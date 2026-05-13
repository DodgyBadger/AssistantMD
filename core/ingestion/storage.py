"""
Storage helpers for writing rendered artifacts to vaults.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from core.ingestion.models import RenderOptions
from core.runtime.paths import get_data_root
from core.vault_state.file_mutations import (
    delete_vault_file,
    write_vault_file,
    write_vault_file_bytes,
)


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
        if "content_bytes" in artifact:
            content_bytes = artifact["content_bytes"]
            if not isinstance(content_bytes, (bytes, bytearray)):
                raise ValueError(f"Binary artifact content_bytes must be bytes for {rel_path.as_posix()}")
            write_vault_file_bytes(
                vault_path=vault_root,
                path=rel_path.as_posix(),
                content=bytes(content_bytes),
                warn_without_task=False,
            )
        else:
            content = artifact["content"]
            write_vault_file(
                vault_path=vault_root,
                path=rel_path.as_posix(),
                content=content,
                warn_without_task=False,
            )
        # Return vault-relative path for API/status reporting
        outputs.append(rel_path.as_posix())

    # Clean up source file after successful write to avoid clutter in vaults
    if options.source_filename:
        try:
            source_path = Path(options.source_filename).resolve()
            # Only delete files under the current vault to avoid unintended removals
            try:
                relative_source = source_path.relative_to(vault_root.resolve()).as_posix()
            except ValueError:
                relative_source = None
            if relative_source and source_path.is_file():
                delete_vault_file(
                    vault_path=vault_root,
                    path=relative_source,
                    warn_without_task=False,
                )
        except Exception:
            # Swallow cleanup errors; ingestion output already written
            pass

    return outputs
