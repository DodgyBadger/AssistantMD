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
    GoogleConnectionCreate,
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
                created.oauth_generation,
                created.display_name,
                created.slug,
                created.is_default,
            ),
            (
                "owner.apps.googleusercontent.com",
                20,
                100,
                50_000,
                25,
                1,
                1,
                "Google",
                "google",
                True,
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
                updated.oauth_generation,
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
                2,
            ),
            "Client identity updates should persist preferences and advance OAuth generation",
        )

        preferences_only = service.set_google_connection_for_authority(
            owner,
            GoogleConnectionUpdate(
                client_id=updated.client_id,
                gmail=GmailPreferences(
                    search_default_results=12,
                    search_max_results=40,
                    message_max_characters=75_000,
                    thread_max_messages=30,
                ),
            ),
        )
        self.soft_assert_equal(
            (preferences_only.config_version, preferences_only.oauth_generation),
            (3, 2),
            "Non-identity edits should advance config version without invalidating OAuth",
        )

        secondary = service.create_google_connection_for_authority(
            owner,
            GoogleConnectionCreate(
                display_name="Work Gmail",
                client_id="work.apps.googleusercontent.com",
            ),
        )
        self.soft_assert_equal(
            (secondary.slug, secondary.is_default),
            ("work-gmail", False),
            "Additional Google connections should have stable slugs without replacing the default",
        )
        self.soft_assert_equal(
            len(service.list_google_connections_for_authority(owner)),
            2,
            "One principal should own multiple Google connections",
        )
        duplicate_rejected = False
        try:
            service.create_google_connection_for_authority(
                owner,
                GoogleConnectionCreate(
                    display_name="work gmail",
                    client_id="duplicate.apps.googleusercontent.com",
                ),
            )
        except ValueError:
            duplicate_rejected = True
        self.soft_assert(
            duplicate_rejected,
            "Google display names should be unique per principal regardless of case",
        )

        promoted = service.update_google_connection_for_authority(
            owner,
            secondary.connection_id,
            GoogleConnectionUpdate(
                display_name=secondary.display_name,
                client_id=secondary.client_id,
                is_default=True,
                gmail=secondary.gmail,
            ),
        )
        self.soft_assert(promoted.is_default, "A second connection can become default")
        self.soft_assert_equal(
            service.get_google_connection_for_authority(owner).connection_id,
            secondary.connection_id,
            "Compatibility access should resolve the effective default",
        )

        protected_default = False
        try:
            service.delete_google_connection_for_authority(
                owner, secondary.connection_id
            )
        except ValueError:
            protected_default = True
        self.soft_assert(
            protected_default,
            "Deleting a default should require an explicit replacement",
        )
        self.soft_assert(
            service.delete_google_connection_for_authority(
                owner,
                secondary.connection_id,
                replacement_default_id=created.connection_id,
            ),
            "The default should be deletable with an explicit replacement",
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
            service.delete_google_connection_for_authority(
                owner, created.connection_id
            ),
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
