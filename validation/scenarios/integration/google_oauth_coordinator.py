"""Deterministic validation of Google OAuth authorization and refresh."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

_direct_run_root: tempfile.TemporaryDirectory[str] | None = None
if __name__ == "__main__":
    from core.runtime.paths import set_bootstrap_roots

    _direct_run_root = tempfile.TemporaryDirectory(prefix="assistantmd-google-oauth-")
    direct_root = Path(_direct_run_root.name)
    data_root = direct_root / "data"
    bootstrap_system_root = direct_root / "system"
    data_root.mkdir()
    bootstrap_system_root.mkdir()
    set_bootstrap_roots(data_root=data_root, system_root=bootstrap_system_root)

from core.connections import (  # noqa: E402
    BuiltInConnectionService,
    GoogleConnectionCreate,
    GoogleConnectionUpdate,
)
from core.identity import ExecutionAuthority  # noqa: E402
from core.integrations.google import (  # noqa: E402
    GMAIL_READONLY_SCOPE,
    GoogleCapability,
    GoogleConnectionService,
    GoogleOAuthCoordinator,
    GoogleOAuthError,
    GoogleOAuthTokenState,
)
from core.secrets import EncryptedSecretsService, SecretKeyring  # noqa: E402
from validation.core.base_scenario import BaseScenario  # noqa: E402


class GoogleOAuthCoordinatorScenario(BaseScenario):
    """Prove headless callback, identity, scope, and refresh contracts."""

    async def test_scenario(self) -> None:
        system_root = self.run_path / "system"
        system_root.mkdir()
        connections = BuiltInConnectionService(system_root=str(system_root))
        secrets = EncryptedSecretsService(
            system_root=str(system_root),
            keyring=SecretKeyring(keys={1: bytes(range(32))}, active_version=1),
        )
        google = GoogleConnectionService(connections=connections, secrets=secrets)
        owner = ExecutionAuthority("google-oauth-owner")
        connections.set_google_connection_for_authority(
            owner,
            GoogleConnectionUpdate(client_id="client.apps.googleusercontent.com"),
        )
        google.set_client_secret(owner, "client-secret")
        requests: list[httpx.Request] = []
        coordinator = GoogleOAuthCoordinator(
            connections=connections,
            google=google,
            secrets=secrets,
            http_client_factory=lambda: _oauth_client(requests),
        )
        secondary = connections.create_google_connection_for_authority(
            owner,
            GoogleConnectionCreate(
                display_name="Secondary Google",
                client_id="secondary.apps.googleusercontent.com",
            ),
        )
        google.set_client_secret(owner, "secondary-secret", secondary.connection_id)

        started = coordinator.start(
            authority=owner,
            redirect_uri="https://assistant.example/api/system/connections/google/oauth/callback",
            capabilities=(GoogleCapability.GMAIL_READ,),
        )
        query = parse_qs(urlparse(started.authorization_url).query)
        self.soft_assert_equal(
            (
                query.get("access_type"),
                query.get("include_granted_scopes"),
                query.get("code_challenge_method"),
                GMAIL_READONLY_SCOPE in query.get("scope", [""])[0],
            ),
            (["offline"], ["true"], ["S256"], True),
            "Google authorization should request offline incremental PKCE consent",
        )
        state = query["state"][0]
        secondary_started = coordinator.start(
            authority=owner,
            redirect_uri=started.redirect_uri,
            capabilities=(GoogleCapability.GMAIL_READ,),
            connection_id=secondary.connection_id,
        )
        secondary_state = parse_qs(urlparse(secondary_started.authorization_url).query)[
            "state"
        ][0]
        completed = await coordinator.complete(
            authority=owner,
            code="authorization-code",
            state=state,
        )
        self.soft_assert_equal(
            (
                completed.account_email,
                completed.refresh_token,
                google.status(owner).state,
            ),
            ("owner@example.com", "initial-refresh-token", "ready"),
            "OAuth completion should verify identity and persist a ready grant",
        )
        secondary_completed = await coordinator.complete(
            authority=owner,
            code="secondary-authorization-code",
            state=secondary_state,
        )
        self.soft_assert_equal(
            (
                secondary_completed.account_email,
                google.status(owner, secondary.connection_id).state,
            ),
            ("owner@example.com", "ready"),
            "A shared callback should resolve the pending non-default connection by state",
        )

        refreshed = await coordinator.refresh(owner)
        self.soft_assert_equal(
            (refreshed.access_token, refreshed.refresh_token),
            ("refreshed-access-token", "initial-refresh-token"),
            "Refresh should preserve Google's omitted refresh token",
        )
        google.save_token_state(
            owner,
            GoogleOAuthTokenState(
                access_token="expired-access-token",
                refresh_token="initial-refresh-token",
                expires_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
                scopes=completed.scopes,
                account_id=completed.account_id,
                account_email=completed.account_email,
            ),
        )
        refresh_count_before = sum(
            b"grant_type=refresh_token" in request.content for request in requests
        )
        concurrent_tokens = await asyncio.gather(
            coordinator.access_token(owner),
            coordinator.access_token(owner),
            coordinator.access_token(owner),
        )
        refresh_count_after = sum(
            b"grant_type=refresh_token" in request.content for request in requests
        )
        self.soft_assert_equal(
            (concurrent_tokens, refresh_count_after - refresh_count_before),
            (["refreshed-access-token"] * 3, 1),
            "Concurrent callers should share one serialized token refresh",
        )
        self.soft_assert(
            any(
                request.url.path.endswith("/token")
                and b"code_verifier=" in request.content
                for request in requests
            ),
            "Authorization completion should send the persisted PKCE verifier",
        )

        try:
            await coordinator.complete(
                authority=owner,
                code="replayed-code",
                state=state,
            )
        except GoogleOAuthError:
            pass
        else:
            self.soft_assert(False, "Completed Google OAuth state must be single-use")

        self.assert_no_failures()
        self.teardown_scenario()


def _oauth_client(requests: list[httpx.Request]) -> httpx.AsyncClient:
    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/token"):
            if b"grant_type=refresh_token" in request.content:
                return httpx.Response(
                    200,
                    json={
                        "access_token": "refreshed-access-token",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                    },
                )
            return httpx.Response(
                200,
                json={
                    "access_token": "initial-access-token",
                    "refresh_token": "initial-refresh-token",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": (
                        "openid https://www.googleapis.com/auth/userinfo.email "
                        f"{GMAIL_READONLY_SCOPE}"
                    ),
                },
            )
        if request.url.path.endswith("/v1/userinfo"):
            return httpx.Response(
                200,
                json={"sub": "owner-account", "email": "owner@example.com"},
            )
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(respond))


if __name__ == "__main__":
    asyncio.run(GoogleOAuthCoordinatorScenario().test_scenario())
