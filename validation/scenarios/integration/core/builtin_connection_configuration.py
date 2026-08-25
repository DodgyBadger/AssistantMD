"""Validate principal-owned built-in connection metadata contracts."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

_direct_run_root: tempfile.TemporaryDirectory[str] | None = None
if __name__ == "__main__":
    from core.runtime.paths import set_bootstrap_roots

    _direct_run_root = tempfile.TemporaryDirectory(
        prefix="assistantmd-builtin-connections-"
    )
    direct_root = Path(_direct_run_root.name)
    data_root = direct_root / "data"
    bootstrap_system_root = direct_root / "system"
    data_root.mkdir()
    bootstrap_system_root.mkdir()
    set_bootstrap_roots(data_root=data_root, system_root=bootstrap_system_root)

from core.connections import (  # noqa: E402
    BuiltInConnectionService,
    GmailPreferences,
    GoogleConnectionUpdate,
)
from core.identity import ExecutionAuthority  # noqa: E402
from validation.core.base_scenario import BaseScenario  # noqa: E402


class BuiltInConnectionConfigurationScenario(BaseScenario):
    """Prove Google metadata and Gmail preferences are owner-scoped."""

    def test_scenario(self) -> None:
        system_root = self.run_path / "system"
        system_root.mkdir()
        service = BuiltInConnectionService(system_root=str(system_root))
        owner = ExecutionAuthority("google-owner")
        other = ExecutionAuthority("google-other")

        created = service.set_google_connection_for_authority(
            owner,
            GoogleConnectionUpdate(client_id="owner.apps.googleusercontent.com"),
        )
        self.soft_assert_equal(
            (
                created.client_id,
                created.gmail.search_default_results,
                created.gmail.search_max_results,
                created.gmail.message_max_characters,
                created.gmail.thread_max_messages,
                created.config_version,
            ),
            (
                "owner.apps.googleusercontent.com",
                20,
                100,
                50_000,
                25,
                1,
            ),
            "Google connection creation should apply accepted Gmail defaults",
        )
        self.soft_assert_equal(
            service.get_google_connection_for_authority(other),
            None,
            "Another principal must not see Google connection metadata",
        )

        updated = service.set_google_connection_for_authority(
            owner,
            GoogleConnectionUpdate(
                client_id="replacement.apps.googleusercontent.com",
                gmail=GmailPreferences(
                    search_default_results=10,
                    search_max_results=40,
                    message_max_characters=75_000,
                    thread_max_messages=30,
                ),
            ),
        )
        self.soft_assert_equal(
            (
                updated.client_id,
                updated.gmail,
                updated.config_version,
            ),
            (
                "replacement.apps.googleusercontent.com",
                GmailPreferences(
                    search_default_results=10,
                    search_max_results=40,
                    message_max_characters=75_000,
                    thread_max_messages=30,
                ),
                2,
            ),
            "Google connection updates should persist typed preferences and version",
        )

        invalid_cases = (
            {"search_default_results": 101, "search_max_results": 100},
            {"search_default_results": 1, "search_max_results": 501},
            {"message_max_characters": 250_001},
            {"thread_max_messages": 101},
        )
        for invalid in invalid_cases:
            try:
                GmailPreferences(**invalid)
            except ValueError:
                pass
            else:
                self.soft_assert(
                    False,
                    f"Invalid Gmail preferences should be rejected: {invalid}",
                )

        self.soft_assert(
            service.delete_google_connection_for_authority(owner),
            "The owner should be able to remove Google connection metadata",
        )
        self.soft_assert_equal(
            service.get_google_connection_for_authority(owner),
            None,
            "Deleted Google connection metadata should remain absent",
        )
        self.assert_no_failures()
        self.teardown_scenario()


if __name__ == "__main__":
    BuiltInConnectionConfigurationScenario().test_scenario()
