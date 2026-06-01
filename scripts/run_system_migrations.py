#!/usr/bin/env python3
"""Run registered AssistantMD system database migrations."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run registered AssistantMD system database migrations.")
    parser.add_argument(
        "--system-root",
        default=str(REPO_ROOT / "system"),
        help="Path to the AssistantMD system directory. Defaults to ./system.",
    )
    parser.add_argument(
        "--skip-backup",
        action="store_true",
        help="Do not create timestamped database backups before applying pending migrations.",
    )
    parser.add_argument(
        "--status-only",
        action="store_true",
        help="Report migration status without modifying databases.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )
    args = parser.parse_args()

    system_root = Path(args.system_root).expanduser().resolve()
    _set_bootstrap_roots(system_root)

    from core.system_migrations import get_system_migration_status, run_system_migrations

    status = (
        get_system_migration_status(system_root)
        if args.status_only
        else run_system_migrations(system_root, backup=not args.skip_backup)
    )

    if args.json:
        print(json.dumps(_status_payload(status), indent=2, sort_keys=True))
    else:
        _print_status(status, status_only=args.status_only)
    return 0


def _set_bootstrap_roots(system_root: Path) -> None:
    from core.runtime.paths import resolve_bootstrap_data_root, set_bootstrap_roots

    set_bootstrap_roots(resolve_bootstrap_data_root(), system_root)


def _status_payload(status) -> dict[str, object]:
    payload = asdict(status)
    payload["pending_count"] = status.pending_count
    return payload


def _print_status(status, *, status_only: bool) -> None:
    heading = "System database migration status" if status_only else "System database migrations completed"
    print(heading)
    print(f"System root: {status.system_root}")
    print(f"Pending migrations: {status.pending_count}")
    for target in status.targets:
        applied = ", ".join(str(version) for version in target.applied_versions) or "(none)"
        pending = ", ".join(str(version) for version in target.pending_versions) or "(none)"
        exists = "yes" if target.exists else "no"
        print(f"\n{target.db_name} [{target.namespace}]")
        print(f"  path: {target.db_path}")
        print(f"  exists: {exists}")
        print(f"  applied: {applied}")
        print(f"  pending: {pending}")
        if target.backup_path:
            print(f"  backup: {target.backup_path}")


if __name__ == "__main__":
    raise SystemExit(main())
