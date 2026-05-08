"""Integration scenario for scheduled vault-state refresh registration."""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from core.scheduling.system_jobs import (
    INGESTION_WORKER_JOB_ID,
    VAULT_STATE_REFRESH_JOB_ID,
    run_scheduled_vault_state_refresh,
)
from core.settings.store import SETTINGS_TEMPLATE
from validation.core.base_scenario import BaseScenario


class VaultStateScheduledRefreshScenario(BaseScenario):
    """Validate scheduled whole-vault observation system job behavior."""

    async def test_scenario(self):
        vault = self.create_vault("VaultStateScheduledRefreshVault")
        self.create_file(vault, "notes/external.md", "External v1\n")
        self._write_vault_scan_interval(60)

        await self.start_system()

        from core.vault_state import VaultStateService

        controller = self._get_system_controller()
        scheduler = controller._runtime.scheduler
        job = scheduler.get_job(VAULT_STATE_REFRESH_JOB_ID)
        self.soft_assert(
            job is not None,
            "Vault-state refresh system job should be registered",
        )
        if job is not None:
            self.soft_assert_equal(
                job.name,
                "Vault state refresh",
                "System job should have a clear display name",
            )
            self.soft_assert_equal(
                job.max_instances,
                1,
                "Vault-state refresh job should not overlap",
            )

        await controller.trigger_vault_rescan()
        self.soft_assert(
            scheduler.get_job(VAULT_STATE_REFRESH_JOB_ID) is not None,
            "Workflow reload should preserve the vault-state system job",
        )
        self.soft_assert(
            scheduler.get_job(INGESTION_WORKER_JOB_ID) is not None,
            "Workflow reload should preserve the ingestion system job",
        )

        service = VaultStateService()
        initial_events = service.changes_since(0)
        checkpoint = max((event.sequence for event in initial_events), default=0)

        (vault / "notes" / "external.md").write_text("External v2\n", encoding="utf-8")
        run_scheduled_vault_state_refresh(controller.test_data_root)

        changes = service.changes_since(checkpoint)
        self.soft_assert(
            any(
                event.path == "notes/external.md" and event.event_type == "changed"
                for event in changes
            ),
            "Scheduled refresh callable should observe external file edits",
        )

        update_setting = self.call_api(
            "/api/system/settings/general/vault_scan_interval_seconds",
            method="PUT",
            data={"value": "0"},
        )
        self.soft_assert_equal(
            update_setting.status_code,
            200,
            "Disabling vault scan interval should be accepted",
        )
        self.soft_assert(
            scheduler.get_job(VAULT_STATE_REFRESH_JOB_ID) is None,
            "Settings reload should remove the persisted vault-state refresh job",
        )
        self.soft_assert(
            scheduler.get_job(INGESTION_WORKER_JOB_ID) is not None,
            "Disabling vault-state refresh should not remove ingestion worker",
        )

        await self.stop_system()
        self.teardown_scenario()
        self.assert_no_failures()

    def _write_vault_scan_interval(self, interval_seconds: int) -> None:
        from core.settings.store import refresh_settings_cache

        settings_path = self._get_system_controller()._system_root / "settings.yaml"
        raw = yaml.safe_load(SETTINGS_TEMPLATE.read_text(encoding="utf-8")) or {}
        raw["settings"]["vault_scan_interval_seconds"]["value"] = interval_seconds
        settings_path.write_text(
            yaml.safe_dump(raw, sort_keys=False, allow_unicode=False),
            encoding="utf-8",
        )
        refresh_settings_cache()
