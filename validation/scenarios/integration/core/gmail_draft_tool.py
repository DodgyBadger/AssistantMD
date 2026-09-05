"""Validate Gmail draft policy, capability, and tool boundaries."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

_direct_run_root: tempfile.TemporaryDirectory[str] | None = None
if __name__ == "__main__":
    from core.runtime.paths import set_bootstrap_roots

    _direct_run_root = tempfile.TemporaryDirectory(prefix="assistantmd-gmail-draft-")
    direct_root = Path(_direct_run_root.name)
    (direct_root / "data").mkdir()
    (direct_root / "system").mkdir()
    set_bootstrap_roots(
        data_root=direct_root / "data", system_root=direct_root / "system"
    )

from core.identity import ExecutionAuthority, use_execution_authority  # noqa: E402
from core.integrations.google.gmail import GmailDraft  # noqa: E402
from core.integrations.google.gmail_service import GmailResourceService  # noqa: E402
from core.tools.gmail import Gmail  # noqa: E402
from validation.core.base_scenario import BaseScenario  # noqa: E402


class GmailDraftToolScenario(BaseScenario):
    """Prove opt-in, scope, bounds, and sanitized draft results."""

    async def test_scenario(self) -> None:
        authority = ExecutionAuthority("gmail-draft-owner")
        selected = SimpleNamespace(
            connection_id="work-id",
            gmail=SimpleNamespace(
                draft_creation_enabled=True,
                draft_max_characters=20,
            ),
        )
        client = _DraftClient()
        google = _GoogleAvailability(available=True)
        service = GmailResourceService(
            connections=object(),  # type: ignore[arg-type]
            google=google,  # type: ignore[arg-type]
            oauth=object(),  # type: ignore[arg-type]
        )
        with (
            patch.object(service, "_resolve_connection", return_value=selected),
            patch.object(service, "_client", return_value=client),
        ):
            result = await service.create_draft(
                authority,
                subject="Hello",
                body="Draft body",
                connection="work",
            )
        self.soft_assert_equal(
            (result.draft_id, client.calls),
            (
                "draft-1",
                [("Hello", "Draft body")],
            ),
            "The service should create one draft after policy and scope checks",
        )

        await self._assert_gate(authority, selected, enabled=False, scope=True)
        await self._assert_gate(authority, selected, enabled=True, scope=False)
        await self._assert_bounds(authority, service, selected)
        await self._assert_tool(authority)
        self.assert_no_failures()
        self.teardown_scenario()

    async def _assert_gate(
        self,
        authority: ExecutionAuthority,
        selected: SimpleNamespace,
        *,
        enabled: bool,
        scope: bool,
    ) -> None:
        selected.gmail.draft_creation_enabled = enabled
        client = _DraftClient()
        service = GmailResourceService(
            connections=object(),  # type: ignore[arg-type]
            google=_GoogleAvailability(available=scope),  # type: ignore[arg-type]
            oauth=object(),  # type: ignore[arg-type]
        )
        with (
            patch.object(service, "_resolve_connection", return_value=selected),
            patch.object(service, "_client", return_value=client),
        ):
            try:
                await service.create_draft(
                    authority,
                    subject="Hello",
                    body="Body",
                )
            except ValueError:
                pass
            else:
                self.soft_assert(False, "Draft creation should enforce its gate")
        self.soft_assert_equal(client.calls, [], "Rejected drafts must not reach Gmail")

    async def _assert_bounds(
        self,
        authority: ExecutionAuthority,
        service: GmailResourceService,
        selected: SimpleNamespace,
    ) -> None:
        selected.gmail.draft_creation_enabled = True
        for body in ("", "x" * 21):
            client = _DraftClient()
            with (
                patch.object(service, "_resolve_connection", return_value=selected),
                patch.object(service, "_client", return_value=client),
            ):
                try:
                    await service.create_draft(authority, subject="Hello", body=body)
                except ValueError:
                    pass
                else:
                    self.soft_assert(False, "Invalid draft bounds should be rejected")
            self.soft_assert_equal(
                client.calls, [], "Bound failures must precede Gmail"
            )

    async def _assert_tool(self, authority: ExecutionAuthority) -> None:
        service = _DraftService()
        tool = Gmail.get_tool()
        with (
            use_execution_authority(authority),
            patch(
                "core.tools.gmail.get_runtime_context",
                return_value=SimpleNamespace(gmail=service),
            ),
        ):
            raw = await tool.function(
                operation="create_draft",
                connection="work",
                subject="Hello",
                body="Draft body",
            )
        payload = json.loads(raw)
        self.soft_assert_equal(
            (payload["draft_id"], payload["message_id"], payload["thread_id"]),
            ("draft-1", "message-1", "thread-1"),
            "The tool should expose stable draft handles",
        )
        self.soft_assert(
            "Draft body" not in raw,
            "Draft content must not be echoed in tool results",
        )


class _GoogleAvailability:
    def __init__(self, *, available: bool) -> None:
        self.available = available

    def capability_availability(self, *_args: object) -> SimpleNamespace:
        return SimpleNamespace(available=self.available, missing_scopes=())


class _DraftClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def create_draft(
        self,
        *,
        subject: str,
        body: str,
    ) -> GmailDraft:
        self.calls.append((subject, body))
        return GmailDraft("draft-1", "message-1", "thread-1")


class _DraftService:
    async def create_draft(self, *_args: object, **_kwargs: object) -> GmailDraft:
        return GmailDraft("draft-1", "message-1", "thread-1")


if __name__ == "__main__":
    asyncio.run(GmailDraftToolScenario().test_scenario())
