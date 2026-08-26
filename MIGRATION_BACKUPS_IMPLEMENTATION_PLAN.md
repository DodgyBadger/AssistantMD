# Migration Backup Directory Plan

## Objective

Keep live system databases easy to identify by storing registered database-
migration backups under `system/migration_backups/`.

## Contract

- New managed migration backups use
  `system/migration_backups/<database>.db.backup-<timestamp>`.
- Each migration run relocates legacy root-level files matching the managed
  `*.db.backup-*` pattern into that directory.
- Existing destinations are never overwritten; a collision fails visibly.
- Settings and legacy-secrets backups use the same directory while retaining
  their recognizable `settings.yaml.bak` and `secrets.yaml.bak` names.
- API, CLI, and activity-log backup paths report the new location.
- The one-shot legacy `memory.db` migration uses the same directory.

## Validation

- Extend the system database migration scenario to assert both relocation of a
  legacy backup and creation of new backups in `migration_backups/`.
- Run the focused scenario and the production Python quality gate.
