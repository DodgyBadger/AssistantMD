"""Canonical public-origin configuration contracts."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

_direct_run_root: tempfile.TemporaryDirectory[str] | None = None
if __name__ == "__main__":
    from core.runtime.paths import set_bootstrap_roots

    _direct_run_root = tempfile.TemporaryDirectory(prefix="assistantmd-public-url-")
    direct_root = Path(_direct_run_root.name)
    data_root = direct_root / "data"
    system_root = direct_root / "system"
    data_root.mkdir()
    system_root.mkdir()
    set_bootstrap_roots(data_root=data_root, system_root=system_root)

from core.runtime.config import RuntimeConfig  # noqa: E402
from core.runtime.public_url import PublicOrigin, PublicUrlError  # noqa: E402
from core.settings import AppSettings  # noqa: E402
from validation.core.base_scenario import BaseScenario  # noqa: E402


class PublicUrlConfigurationScenario(BaseScenario):
    """Prove deployment origins normalize safely without network access."""

    async def test_scenario(self) -> None:
        expected = {
            "https://Assistant.Example.com/": "https://assistant.example.com",
            "https://assistant.example.com:8443": (
                "https://assistant.example.com:8443"
            ),
            "http://localhost:8000/": "http://localhost:8000",
            "http://127.42.0.1:8000": "http://127.42.0.1:8000",
            "http://[::1]:8000": "http://[::1]:8000",
        }
        for raw, normalized in expected.items():
            self.soft_assert_equal(
                PublicOrigin.parse(raw).value,
                normalized,
                f"Public origin should normalize {raw}",
            )

        invalid = (
            "http://assistant.example.com",
            "ftp://assistant.example.com",
            "https://user:secret@assistant.example.com",
            "https://assistant.example.com/app",
            "https://assistant.example.com?next=elsewhere",
            "https://assistant.example.com/#fragment",
            "https://assistant.example.com:invalid",
        )
        for raw in invalid:
            try:
                PublicOrigin.parse(raw)
            except PublicUrlError:
                pass
            else:
                self.soft_assert(False, f"Public origin should reject {raw}")

        origin = PublicOrigin.parse("https://assistant.example.com")
        self.soft_assert_equal(
            origin.build_url("/api/system/callback"),
            "https://assistant.example.com/api/system/callback",
            "Canonical origin should build an application callback URL",
        )
        for path in (
            "api/callback",
            "//attacker.example/callback",
            "/../callback",
            "/%2e%2e/callback",
            "/callback?code=secret",
            "/callback#fragment",
            "/callback\\elsewhere",
        ):
            try:
                origin.build_url(path)
            except PublicUrlError:
                pass
            else:
                self.soft_assert(False, f"Application URL should reject {path}")

        settings = AppSettings(ASSISTANTMD_PUBLIC_URL="https://Assistant.Example.com/")
        self.soft_assert_equal(
            settings.public_url,
            "https://assistant.example.com",
            "Infrastructure settings should expose only the normalized origin",
        )
        runtime = RuntimeConfig.for_production(
            data_root=str(self.run_path / "data"),
            system_root=str(self.run_path / "system"),
            public_url=settings.public_url,
        )
        self.soft_assert_equal(
            runtime.public_origin,
            PublicOrigin("https://assistant.example.com"),
            "Production runtime should own the parsed public origin",
        )
        validation_runtime = RuntimeConfig.for_validation(
            self.run_path,
            self.run_path / "validation-data",
        )
        self.soft_assert_equal(
            validation_runtime.public_origin,
            None,
            "Validation runtime should not inherit deployment environment state",
        )

        self.assert_no_failures()
        self.teardown_scenario()


if __name__ == "__main__":
    asyncio.run(PublicUrlConfigurationScenario().test_scenario())
