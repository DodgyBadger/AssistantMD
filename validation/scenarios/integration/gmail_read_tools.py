"""Deterministic Gmail read-resource and tool-boundary validation."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

_direct_run_root: tempfile.TemporaryDirectory[str] | None = None
if __name__ == "__main__":
    from core.runtime.paths import set_bootstrap_roots

    _direct_run_root = tempfile.TemporaryDirectory(prefix="assistantmd-gmail-read-")
    direct_root = Path(_direct_run_root.name)
    data_root = direct_root / "data"
    system_root = direct_root / "system"
    data_root.mkdir()
    system_root.mkdir()
    set_bootstrap_roots(data_root=data_root, system_root=system_root)

from core.integrations.google.gmail import GmailAPIClient  # noqa: E402
from validation.core.base_scenario import BaseScenario  # noqa: E402


class GmailReadToolsScenario(BaseScenario):
    """Prove bounded search, MIME normalization, and attachment metadata."""

    async def test_scenario(self) -> None:
        requests: list[httpx.Request] = []
        client = GmailAPIClient(
            access_token_provider=_access_token,
            http_client_factory=lambda: _gmail_client(requests),
            sleep=_no_sleep,
        )

        search = await client.search(query="from:sender@example.com", max_results=2)
        self.soft_assert_equal(
            ([item.message_id for item in search.messages], search.result_count),
            (["message-1", "message-2"], 2),
            "Search should return stable message handles and a bounded count",
        )

        message = await client.get_message("message-1", max_characters=12)
        self.soft_assert_equal(
            (message.subject, message.text, message.text_truncated),
            ("Known message", "Hello world!", True),
            "Message reads should prefer and bound normalized plain text",
        )
        self.soft_assert_equal(
            (
                len(message.attachments),
                message.attachments[0].filename,
                message.attachments[0].attachment_id,
            ),
            (1, "report.pdf", "attachment-1"),
            "Message reads should expose attachment descriptors without bytes",
        )

        thread = await client.get_thread("thread-1", max_messages=1, max_characters=50)
        self.soft_assert_equal(
            (len(thread.messages), thread.omitted_message_count, thread.truncated),
            (1, 1, True),
            "Thread reads should report bounded message truncation",
        )
        self.soft_assert(
            all(
                request.headers.get("authorization") == "Bearer access-token"
                for request in requests
            ),
            "Every Gmail request should use principal-resolved authorization",
        )
        self.soft_assert(
            all("attachments/" not in request.url.path for request in requests),
            "Read-only Gmail support must never download attachment bytes",
        )

        self.assert_no_failures()
        self.teardown_scenario()


async def _access_token() -> str:
    return "access-token"


async def _no_sleep(_seconds: float) -> None:
    return None


def _gmail_client(requests: list[httpx.Request]) -> httpx.AsyncClient:
    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path.endswith("/messages"):
            return httpx.Response(
                200,
                json={
                    "messages": [
                        {"id": "message-1", "threadId": "thread-1"},
                        {"id": "message-2", "threadId": "thread-2"},
                    ],
                    "resultSizeEstimate": 2,
                },
            )
        if path.endswith("/messages/message-1"):
            return httpx.Response(200, json=_message("message-1", "thread-1"))
        if path.endswith("/messages/message-2"):
            return httpx.Response(200, json=_message("message-2", "thread-2"))
        if path.endswith("/threads/thread-1"):
            return httpx.Response(
                200,
                json={
                    "id": "thread-1",
                    "historyId": "99",
                    "messages": [
                        _message("message-1", "thread-1"),
                        _message("message-3", "thread-1"),
                    ],
                },
            )
        return httpx.Response(404, json={"error": {"message": "not found"}})

    return httpx.AsyncClient(transport=httpx.MockTransport(respond))


def _message(message_id: str, thread_id: str) -> dict[str, object]:
    return {
        "id": message_id,
        "threadId": thread_id,
        "historyId": "42",
        "internalDate": "1700000000000",
        "labelIds": ["INBOX", "UNREAD"],
        "snippet": "Hello world preview",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "Subject", "value": "Known message"},
                {"name": "From", "value": "Sender <sender@example.com>"},
                {"name": "To", "value": "owner@example.com"},
                {"name": "Date", "value": "Tue, 1 Jan 2026 10:00:00 +0000"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": "SGVsbG8gd29ybGQhIEV4dHJh"},
                },
                {
                    "mimeType": "application/pdf",
                    "filename": "report.pdf",
                    "body": {"attachmentId": "attachment-1", "size": 1234},
                },
            ],
        },
    }


if __name__ == "__main__":
    asyncio.run(GmailReadToolsScenario().test_scenario())
