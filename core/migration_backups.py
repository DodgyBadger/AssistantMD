"""Owned paths and organization for migration rollback copies."""

from __future__ import annotations

from pathlib import Path

MIGRATION_BACKUP_DIRECTORY = "migration_backups"
ROOT_BACKUP_FILENAMES = frozenset({"secrets.yaml.bak", "settings.yaml.bak"})


def get_migration_backup_directory(system_root: str | Path) -> Path:
    """Return the migration backup directory without creating it."""
    return Path(system_root) / MIGRATION_BACKUP_DIRECTORY


def organize_legacy_migration_backups(system_root: str | Path) -> int:
    """Move recognized root-level migration backups into their owned directory."""
    root = Path(system_root)
    legacy_paths = sorted(
        {
            *root.glob("*.db.backup-*"),
            *(root / name for name in ROOT_BACKUP_FILENAMES if (root / name).exists()),
        }
    )
    if not legacy_paths:
        return 0
    backup_directory = get_migration_backup_directory(root)
    backup_directory.mkdir(parents=True, exist_ok=True)
    for source in legacy_paths:
        destination = backup_directory / source.name
        if destination.exists():
            raise FileExistsError(
                "Cannot organize migration backup because the destination already "
                f"exists: {destination}"
            )
        source.rename(destination)
    return len(legacy_paths)
