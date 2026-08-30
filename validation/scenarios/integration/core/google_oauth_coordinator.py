"""Deterministic validation of Google OAuth authorization and refresh."""

from __future__ import annotations

import asyncio
import sqlite3
import sys
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

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
    GoogleOAuthStart,
    GoogleOAuthTokenState,
)
from core.oauth import EncryptedOAuthStorage  # noqa: E402
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
        try:
            await coordinator.complete(
                authority=owner,
                code="untrusted-authorization-code",
                state="wrong-state",
            )
        except GoogleOAuthError:
            pass
        else:
            self.soft_assert(False, "Google OAuth should reject a mismatched state")
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
        self.soft_assert(
            completed.access_token == "initial-access-token",
            "A mismatched callback must not consume the legitimate pending attempt",
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

        stale = connections.create_google_connection_for_authority(
            owner,
            GoogleConnectionCreate(
                display_name="Changing Client",
                client_id="changing.apps.googleusercontent.com",
            ),
        )
        google.set_client_secret(owner, "changing-secret", stale.connection_id)
        stale_started = coordinator.start(
            authority=owner,
            redirect_uri=started.redirect_uri,
            capabilities=(GoogleCapability.GMAIL_READ,),
            connection_id=stale.connection_id,
        )
        stale_state = parse_qs(urlparse(stale_started.authorization_url).query)[
            "state"
        ][0]
        connections.update_google_connection_for_authority(
            owner,
            stale.connection_id,
            GoogleConnectionUpdate(
                client_id="replacement.apps.googleusercontent.com",
                display_name=stale.display_name,
                gmail=stale.gmail,
            ),
        )
        token_request_count = sum(
            request.url.path.endswith("/token") for request in requests
        )
        try:
            await coordinator.complete(
                authority=owner,
                connection_id=stale.connection_id,
                code="stale-client-code",
                state=stale_state,
            )
        except GoogleOAuthError:
            pass
        else:
            self.soft_assert(
                False,
                "A callback bound to changed client metadata should be rejected",
            )
        self.soft_assert_equal(
            sum(request.url.path.endswith("/token") for request in requests),
            token_request_count,
            "A stale Google callback must be rejected before token exchange",
        )

        fenced = connections.create_google_connection_for_authority(
            owner,
            GoogleConnectionCreate(
                display_name="In-flight Credential",
                client_id="inflight.apps.googleusercontent.com",
            ),
        )
        google.set_client_secret(owner, "inflight-secret-a", fenced.connection_id)
        captured_credential = google.resolve_client_credential(
            owner, fenced.connection_id
        )
        if captured_credential is None:
            raise AssertionError("Expected the initial in-flight credential")
        google.set_client_secret(owner, "inflight-secret-b", fenced.connection_id)
        try:
            google.save_token_state(
                owner,
                GoogleOAuthTokenState(
                    access_token="stale-inflight-token",
                    refresh_token="stale-inflight-refresh",
                    scopes=(GMAIL_READONLY_SCOPE,),
                    account_id="stale-account",
                    account_email="stale@example.com",
                ),
                fenced.connection_id,
                expected_credential=captured_credential,
            )
        except ValueError:
            pass
        else:
            self.soft_assert(
                False,
                "A token response must not cross an in-flight credential replacement",
            )
        self.soft_assert_equal(
            google.load_token_state(owner, fenced.connection_id),
            None,
            "A rejected in-flight response must not recreate cleared token state",
        )

        for blocked_step in ("token", "identity"):
            for mutation_kind in ("secret", "client-id", "disconnect"):
                await self._assert_completion_race_rejected(
                    connections=connections,
                    secrets=secrets,
                    google=google,
                    owner=owner,
                    redirect_uri=started.redirect_uri,
                    blocked_step=blocked_step,
                    mutation_kind=mutation_kind,
                )

        await self._assert_completion_preserves_newer_pending(
            connections=connections,
            secrets=secrets,
            google=google,
            owner=owner,
            redirect_uri=started.redirect_uri,
        )

        for mutation_kind in ("secret", "client-id", "disconnect"):
            await self._assert_refresh_race_rejected(
                connections=connections,
                secrets=secrets,
                google=google,
                owner=owner,
                mutation_kind=mutation_kind,
            )

        await self._assert_reauthorization_wins_refresh(
            connections=connections,
            secrets=secrets,
            google=google,
            owner=owner,
        )
        await self._assert_disconnect_preserves_concurrent_mutation(
            connections=connections,
            google=google,
            owner=owner,
            mutation_kind="secret",
        )
        await self._assert_disconnect_preserves_concurrent_mutation(
            connections=connections,
            google=google,
            owner=owner,
            mutation_kind="client-id",
        )
        await self._assert_delete_wins_concurrent_secret_write(
            connections=connections,
            secrets=secrets,
            google=google,
            owner=owner,
        )
        self._assert_deletion_cleanup_recovers(
            connections=connections,
            secrets=secrets,
            google=google,
            owner=owner,
        )
        self._assert_new_generation_secret_survives_invalidation(
            connections=connections,
            google=google,
            owner=owner,
        )
        self._assert_legacy_upgrade_cannot_restore_stale_secret(
            connections=connections,
            secrets=secrets,
            google=google,
            owner=owner,
        )
        self._assert_superseded_metadata_cleanup_preserves_new_generation(
            connections=connections,
            secrets=secrets,
            google=google,
            owner=owner,
        )
        self._assert_oauth_start_rejects_concurrent_changes(
            connections=connections,
            secrets=secrets,
            google=google,
            owner=owner,
            redirect_uri=started.redirect_uri,
        )
        self._assert_default_deletion_clears_legacy_before_promotion(
            connections=connections,
            secrets=secrets,
            google=google,
        )

        self.assert_no_failures()
        self.teardown_scenario()

    async def _assert_completion_race_rejected(
        self,
        *,
        connections: BuiltInConnectionService,
        secrets: EncryptedSecretsService,
        google: GoogleConnectionService,
        owner: ExecutionAuthority,
        redirect_uri: str,
        blocked_step: str,
        mutation_kind: str,
    ) -> None:
        raced = connections.create_google_connection_for_authority(
            owner,
            GoogleConnectionCreate(
                display_name=f"Raced {blocked_step} {mutation_kind}",
                client_id=(
                    f"raced-{blocked_step}-{mutation_kind}"
                    ".apps.googleusercontent.com"
                ),
            ),
        )
        google.set_client_secret(owner, "raced-secret-a", raced.connection_id)
        entered = asyncio.Event()
        release = asyncio.Event()
        raced_requests: list[httpx.Request] = []
        raced_coordinator = GoogleOAuthCoordinator(
            connections=connections,
            google=google,
            secrets=secrets,
            http_client_factory=lambda requests=raced_requests, start=entered, finish=release, step=blocked_step: _blocking_oauth_client(
                requests,
                entered=start,
                release=finish,
                blocked_step=step,
            ),
        )
        raced_started = raced_coordinator.start(
            authority=owner,
            redirect_uri=redirect_uri,
            capabilities=(GoogleCapability.GMAIL_READ,),
            connection_id=raced.connection_id,
        )
        raced_state = parse_qs(urlparse(raced_started.authorization_url).query)[
            "state"
        ][0]
        completion = asyncio.create_task(
            raced_coordinator.complete(
                authority=owner,
                connection_id=raced.connection_id,
                code=f"raced-{blocked_step}-code",
                state=raced_state,
            )
        )
        await entered.wait()
        if mutation_kind == "secret":
            google.set_client_secret(owner, "raced-secret-b", raced.connection_id)
        elif mutation_kind == "client-id":
            connections.update_google_connection_for_authority(
                owner,
                raced.connection_id,
                GoogleConnectionUpdate(
                    client_id=(
                        f"replacement-{blocked_step}.apps.googleusercontent.com"
                    ),
                    display_name=raced.display_name,
                    gmail=raced.gmail,
                ),
            )
        else:
            google.clear_token_state(owner, raced.connection_id)
        release.set()
        try:
            await completion
        except GoogleOAuthError:
            pass
        else:
            self.soft_assert(
                False,
                f"{mutation_kind} replacement during {blocked_step} must reject completion",
            )
        self.soft_assert_equal(
            google.load_token_state(owner, raced.connection_id),
            None,
            f"{mutation_kind} replacement during {blocked_step} must not restore a token",
        )

    async def _assert_completion_preserves_newer_pending(
        self,
        *,
        connections: BuiltInConnectionService,
        secrets: EncryptedSecretsService,
        google: GoogleConnectionService,
        owner: ExecutionAuthority,
        redirect_uri: str,
    ) -> None:
        connection = connections.create_google_connection_for_authority(
            owner,
            GoogleConnectionCreate(
                display_name="Conditional pending consumption",
                client_id="conditional-pending.apps.googleusercontent.com",
            ),
        )
        google.set_client_secret(owner, "conditional-secret", connection.connection_id)
        coordinator = GoogleOAuthCoordinator(
            connections=connections,
            google=google,
            secrets=secrets,
        )
        first = coordinator.start(
            authority=owner,
            redirect_uri=redirect_uri,
            capabilities=(GoogleCapability.GMAIL_READ,),
            connection_id=connection.connection_id,
        )
        first_state = parse_qs(urlparse(first.authorization_url).query)["state"][0]
        original_delete = EncryptedOAuthStorage.delete_sync_if_unchanged
        second: list[GoogleOAuthStart] = []
        superseded = False

        def supersede_before_consume(
            target: EncryptedOAuthStorage, *args: object, **kwargs: object
        ) -> bool:
            nonlocal superseded
            if not superseded:
                superseded = True
                second.append(
                    coordinator.start(
                        authority=owner,
                        redirect_uri=redirect_uri,
                        capabilities=(GoogleCapability.GMAIL_READ,),
                        connection_id=connection.connection_id,
                    )
                )
            return original_delete(target, *args, **kwargs)

        with patch.object(
            EncryptedOAuthStorage,
            "delete_sync_if_unchanged",
            supersede_before_consume,
        ):
            try:
                await coordinator.complete(
                    authority=owner,
                    code="superseded-code",
                    state=first_state,
                    connection_id=connection.connection_id,
                )
            except GoogleOAuthError:
                pass
            else:
                self.soft_assert(
                    False, "Completion must reject a superseded pending state"
                )
        stored = EncryptedOAuthStorage(
            secrets=secrets,
            authority=owner,
            namespace=f"oauth.google.{connection.connection_id}",
        ).get_sync("pending-authorization", collection="google")
        second_state = parse_qs(urlparse(second[0].authorization_url).query)["state"][0]
        self.soft_assert_equal(
            stored["state"] if stored is not None else None,
            second_state,
            "Stale completion must preserve a newer pending authorization",
        )

    async def _assert_refresh_race_rejected(
        self,
        *,
        connections: BuiltInConnectionService,
        secrets: EncryptedSecretsService,
        google: GoogleConnectionService,
        owner: ExecutionAuthority,
        mutation_kind: str,
    ) -> None:
        refresh_race = connections.create_google_connection_for_authority(
            owner,
            GoogleConnectionCreate(
                display_name=f"Raced refresh {mutation_kind}",
                client_id=f"raced-refresh-{mutation_kind}.apps.googleusercontent.com",
            ),
        )
        google.set_client_secret(owner, "refresh-secret-a", refresh_race.connection_id)
        google.save_token_state(
            owner,
            GoogleOAuthTokenState(
                access_token="expired-refresh-access",
                refresh_token="refresh-token-a",
                expires_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
                scopes=(GMAIL_READONLY_SCOPE,),
                account_id="refresh-account",
                account_email="refresh@example.com",
            ),
            refresh_race.connection_id,
        )
        refresh_entered = asyncio.Event()
        refresh_release = asyncio.Event()
        refresh_requests: list[httpx.Request] = []
        refresh_coordinator = GoogleOAuthCoordinator(
            connections=connections,
            google=google,
            secrets=secrets,
            http_client_factory=lambda: _blocking_oauth_client(
                refresh_requests,
                entered=refresh_entered,
                release=refresh_release,
                blocked_step="refresh",
            ),
        )
        refresh_task = asyncio.create_task(
            refresh_coordinator.refresh(owner, refresh_race.connection_id)
        )
        await refresh_entered.wait()
        if mutation_kind == "secret":
            google.set_client_secret(
                owner, "refresh-secret-b", refresh_race.connection_id
            )
        elif mutation_kind == "client-id":
            connections.update_google_connection_for_authority(
                owner,
                refresh_race.connection_id,
                GoogleConnectionUpdate(
                    client_id="replacement-refresh.apps.googleusercontent.com",
                    display_name=refresh_race.display_name,
                    gmail=refresh_race.gmail,
                ),
            )
        else:
            google.clear_token_state(owner, refresh_race.connection_id)
        refresh_release.set()
        try:
            await refresh_task
        except GoogleOAuthError:
            pass
        else:
            self.soft_assert(
                False,
                f"{mutation_kind} replacement during refresh must reject the stale response",
            )
        self.soft_assert_equal(
            google.load_token_state(owner, refresh_race.connection_id),
            None,
            f"{mutation_kind} replacement during refresh must not restore a stale token",
        )

    async def _assert_reauthorization_wins_refresh(
        self,
        *,
        connections: BuiltInConnectionService,
        secrets: EncryptedSecretsService,
        google: GoogleConnectionService,
        owner: ExecutionAuthority,
    ) -> None:
        connection = connections.create_google_connection_for_authority(
            owner,
            GoogleConnectionCreate(
                display_name="Refresh versus reauthorization",
                client_id="refresh-reauth.apps.googleusercontent.com",
            ),
        )
        google.set_client_secret(
            owner, "refresh-reauth-secret", connection.connection_id
        )
        initial = GoogleOAuthTokenState(
            access_token="refresh-reauth-expired",
            refresh_token="refresh-reauth-old-token",
            expires_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
            scopes=(GMAIL_READONLY_SCOPE,),
            account_id="refresh-reauth-account",
            account_email="refresh-reauth@example.com",
        )
        google.save_token_state(owner, initial, connection.connection_id)
        entered = asyncio.Event()
        release = asyncio.Event()
        coordinator = GoogleOAuthCoordinator(
            connections=connections,
            google=google,
            secrets=secrets,
            http_client_factory=lambda: _blocking_oauth_client(
                [],
                entered=entered,
                release=release,
                blocked_step="refresh",
            ),
        )
        refresh_task = asyncio.create_task(
            coordinator.refresh(owner, connection.connection_id)
        )
        await entered.wait()
        newer = GoogleOAuthTokenState(
            access_token="reauthorized-access",
            refresh_token="reauthorized-refresh",
            scopes=(GMAIL_READONLY_SCOPE,),
            account_id=initial.account_id,
            account_email=initial.account_email,
        )
        google.save_token_state(owner, newer, connection.connection_id)
        release.set()
        try:
            await refresh_task
        except GoogleOAuthError:
            pass
        else:
            self.soft_assert(False, "An old refresh must not overwrite reauthorization")
        self.soft_assert_equal(
            google.load_token_state(owner, connection.connection_id),
            newer,
            "The newer reauthorization grant must remain authoritative",
        )

    async def _assert_disconnect_preserves_concurrent_mutation(
        self,
        *,
        connections: BuiltInConnectionService,
        google: GoogleConnectionService,
        owner: ExecutionAuthority,
        mutation_kind: str,
    ) -> None:
        connection = connections.create_google_connection_for_authority(
            owner,
            GoogleConnectionCreate(
                display_name=f"Disconnect versus {mutation_kind}",
                client_id=f"disconnect-{mutation_kind}.apps.googleusercontent.com",
            ),
        )
        google.set_client_secret(owner, "disconnect-secret-a", connection.connection_id)
        captured = threading.Event()
        release = threading.Event()
        original_resolve = google.resolve_client_credential

        def paused_resolve(
            authority: ExecutionAuthority, connection_id: str | None = None
        ):
            credential = original_resolve(authority, connection_id)
            if not captured.is_set():
                captured.set()
                if not release.wait(timeout=5):
                    raise TimeoutError("Timed out waiting to release disconnect")
            return credential

        with patch.object(
            google, "resolve_client_credential", side_effect=paused_resolve
        ):
            disconnect_task = asyncio.create_task(
                asyncio.to_thread(
                    google.clear_token_state, owner, connection.connection_id
                )
            )
            await asyncio.to_thread(captured.wait, 5)
            if mutation_kind == "secret":
                google.set_client_secret(
                    owner, "disconnect-secret-b", connection.connection_id
                )
                expected_secret = "disconnect-secret-b"
            else:
                updated = connections.update_google_connection_for_authority(
                    owner,
                    connection.connection_id,
                    GoogleConnectionUpdate(
                        client_id="disconnect-replacement.apps.googleusercontent.com",
                        display_name=connection.display_name,
                        gmail=connection.gmail,
                    ),
                )
                google.handle_metadata_update(owner, connection, updated)
                expected_secret = None
            release.set()
            await disconnect_task
        self.soft_assert_equal(
            google.resolve_client_secret(owner, connection.connection_id),
            expected_secret,
            f"Disconnect must not revert a concurrent {mutation_kind} mutation",
        )

    async def _assert_delete_wins_concurrent_secret_write(
        self,
        *,
        connections: BuiltInConnectionService,
        secrets: EncryptedSecretsService,
        google: GoogleConnectionService,
        owner: ExecutionAuthority,
    ) -> None:
        connection = connections.create_google_connection_for_authority(
            owner,
            GoogleConnectionCreate(
                display_name="Delete versus secret write",
                client_id="delete-secret.apps.googleusercontent.com",
            ),
        )
        google.set_client_secret(owner, "delete-secret-a", connection.connection_id)
        captured = threading.Event()
        release = threading.Event()
        original_connection = google._connection

        def paused_connection(authority: ExecutionAuthority, connection_id: str | None):
            resolved = original_connection(authority, connection_id)
            if not captured.is_set():
                captured.set()
                if not release.wait(timeout=5):
                    raise TimeoutError("Timed out waiting to release secret write")
            return resolved

        errors: list[BaseException] = []

        def write_secret() -> None:
            try:
                google.set_client_secret(
                    owner, "delete-secret-b", connection.connection_id
                )
            except BaseException as exc:  # noqa: BLE001 - surfaced to scenario
                errors.append(exc)

        with patch.object(google, "_connection", side_effect=paused_connection):
            writer = threading.Thread(target=write_secret)
            writer.start()
            self.soft_assert(
                captured.wait(timeout=5),
                "Concurrent secret write should capture connection metadata",
            )
            connections.delete_google_connection_for_authority(
                owner, connection.connection_id
            )
            google.reconcile_connection_deletion(owner, connection.connection_id)
            release.set()
            writer.join(timeout=5)
        self.soft_assert_equal(
            (
                writer.is_alive(),
                errors,
                secrets.list_metadata_for_authority(
                    owner, f"oauth.google.{connection.connection_id}"
                ),
            ),
            (False, [], []),
            "Connection deletion must not leave a concurrently written secret orphan",
        )

    def _assert_deletion_cleanup_recovers(
        self,
        *,
        connections: BuiltInConnectionService,
        secrets: EncryptedSecretsService,
        google: GoogleConnectionService,
        owner: ExecutionAuthority,
    ) -> None:
        connection = connections.create_google_connection_for_authority(
            owner,
            GoogleConnectionCreate(
                display_name="Recoverable deletion",
                client_id="recoverable-delete.apps.googleusercontent.com",
            ),
        )
        google.set_client_secret(owner, "recoverable-secret", connection.connection_id)
        connections.delete_google_connection_for_authority(
            owner, connection.connection_id
        )
        with patch.object(
            secrets,
            "mutate_for_authority",
            side_effect=sqlite3.OperationalError("injected cleanup failure"),
        ):
            try:
                google.reconcile_connection_deletion(owner, connection.connection_id)
            except sqlite3.OperationalError:
                pass
            else:
                self.soft_assert(False, "Injected deletion cleanup should fail")
        self.soft_assert(
            connections.has_google_connection_deletion_for_authority(
                owner, connection.connection_id
            ),
            "Failed encrypted cleanup must preserve its durable deletion record",
        )
        google.reconcile_connection_deletion(owner, connection.connection_id)
        self.soft_assert_equal(
            (
                connections.has_google_connection_deletion_for_authority(
                    owner, connection.connection_id
                ),
                secrets.list_metadata_for_authority(
                    owner, f"oauth.google.{connection.connection_id}"
                ),
            ),
            (True, []),
            "Retry should finish cleanup while retaining the deletion ledger",
        )
        secrets.set_for_authority(
            owner,
            f"oauth.google.{connection.connection_id}",
            "post-cleanup-crash-orphan",
            "orphaned-secret",
        )
        google.reconcile_connection_deletions()
        self.soft_assert_equal(
            secrets.list_metadata_for_authority(
                owner, f"oauth.google.{connection.connection_id}"
            ),
            [],
            "Startup reconciliation must purge state recreated after prior cleanup",
        )

    def _assert_new_generation_secret_survives_invalidation(
        self,
        *,
        connections: BuiltInConnectionService,
        google: GoogleConnectionService,
        owner: ExecutionAuthority,
    ) -> None:
        previous = connections.create_google_connection_for_authority(
            owner,
            GoogleConnectionCreate(
                display_name="Concurrent new generation",
                client_id="generation-a.apps.googleusercontent.com",
            ),
        )
        google.set_client_secret(owner, "generation-secret-a", previous.connection_id)
        updated = connections.update_google_connection_for_authority(
            owner,
            previous.connection_id,
            GoogleConnectionUpdate(
                client_id="generation-b.apps.googleusercontent.com",
                display_name=previous.display_name,
                gmail=previous.gmail,
            ),
        )
        google.set_client_secret(owner, "generation-secret-b", updated.connection_id)
        google.handle_metadata_update(owner, previous, updated)
        self.soft_assert_equal(
            google.resolve_client_secret(owner, updated.connection_id),
            "generation-secret-b",
            "Old-generation invalidation must preserve a new-generation credential",
        )

    def _assert_legacy_upgrade_cannot_restore_stale_secret(
        self,
        *,
        connections: BuiltInConnectionService,
        secrets: EncryptedSecretsService,
        google: GoogleConnectionService,
        owner: ExecutionAuthority,
    ) -> None:
        connection = connections.create_google_connection_for_authority(
            owner,
            GoogleConnectionCreate(
                display_name="Legacy upgrade race",
                client_id="legacy-upgrade-race.apps.googleusercontent.com",
            ),
        )
        storage = EncryptedOAuthStorage(
            secrets=secrets,
            authority=owner,
            namespace=f"oauth.google.{connection.connection_id}",
        )
        storage.put_sync(
            "client-secret", {"value": "legacy-raced-secret"}, collection="google"
        )
        original_put = EncryptedOAuthStorage.put_sync_if_unchanged
        replaced = False

        def replace_before_upgrade(
            target: EncryptedOAuthStorage, *args: object, **kwargs: object
        ) -> float | None:
            nonlocal replaced
            if not replaced:
                replaced = True
                google.set_client_secret(
                    owner, "newer-raced-secret", connection.connection_id
                )
            return original_put(target, *args, **kwargs)

        with patch.object(
            EncryptedOAuthStorage,
            "put_sync_if_unchanged",
            replace_before_upgrade,
        ):
            resolved = google.resolve_client_secret(owner, connection.connection_id)
        self.soft_assert_equal(
            resolved,
            "newer-raced-secret",
            "Legacy binding CAS must not restore a replaced credential",
        )
        post_cas = connections.create_google_connection_for_authority(
            owner,
            GoogleConnectionCreate(
                display_name="Post-CAS legacy upgrade race",
                client_id="post-cas-legacy-upgrade.apps.googleusercontent.com",
            ),
        )
        post_cas_storage = EncryptedOAuthStorage(
            secrets=secrets,
            authority=owner,
            namespace=f"oauth.google.{post_cas.connection_id}",
        )
        post_cas_storage.put_sync(
            "client-secret", {"value": "post-cas-secret-a"}, collection="google"
        )
        post_cas_replaced = False

        def replace_after_upgrade(
            target: EncryptedOAuthStorage, *args: object, **kwargs: object
        ) -> float | None:
            nonlocal post_cas_replaced
            result = original_put(target, *args, **kwargs)
            if not post_cas_replaced:
                post_cas_replaced = True
                google.set_client_secret(
                    owner, "post-cas-secret-b", post_cas.connection_id
                )
            return result

        with patch.object(
            EncryptedOAuthStorage,
            "put_sync_if_unchanged",
            replace_after_upgrade,
        ):
            post_cas_resolved = google.resolve_client_secret(
                owner, post_cas.connection_id
            )
        self.soft_assert_equal(
            post_cas_resolved,
            "post-cas-secret-b",
            "Legacy binding must reauthorize after its successful CAS",
        )
        deleted = connections.create_google_connection_for_authority(
            owner,
            GoogleConnectionCreate(
                display_name="Deleted legacy upgrade race",
                client_id="deleted-legacy-upgrade.apps.googleusercontent.com",
            ),
        )
        deleted_storage = EncryptedOAuthStorage(
            secrets=secrets,
            authority=owner,
            namespace=f"oauth.google.{deleted.connection_id}",
        )
        deleted_storage.put_sync(
            "client-secret", {"value": "deleted-legacy-secret"}, collection="google"
        )
        removed = False

        def delete_after_upgrade(
            target: EncryptedOAuthStorage, *args: object, **kwargs: object
        ) -> float | None:
            nonlocal removed
            result = original_put(target, *args, **kwargs)
            if not removed:
                removed = True
                connections.delete_google_connection_for_authority(
                    owner, deleted.connection_id
                )
            return result

        with patch.object(
            EncryptedOAuthStorage,
            "put_sync_if_unchanged",
            delete_after_upgrade,
        ):
            deleted_result = google.resolve_client_secret(owner, deleted.connection_id)
        self.soft_assert_equal(
            (
                deleted_result,
                deleted_storage.get_sync("client-secret", collection="google"),
            ),
            (None, None),
            "A deleted connection must conditionally remove its raced legacy upgrade",
        )

    def _assert_superseded_metadata_cleanup_preserves_new_generation(
        self,
        *,
        connections: BuiltInConnectionService,
        secrets: EncryptedSecretsService,
        google: GoogleConnectionService,
        owner: ExecutionAuthority,
    ) -> None:
        generation_a = connections.create_google_connection_for_authority(
            owner,
            GoogleConnectionCreate(
                display_name="Superseded metadata cleanup",
                client_id="superseded-a.apps.googleusercontent.com",
            ),
        )
        google.set_client_secret(
            owner, "superseded-secret-a", generation_a.connection_id
        )
        generation_b = connections.update_google_connection_for_authority(
            owner,
            generation_a.connection_id,
            GoogleConnectionUpdate(
                client_id="superseded-b.apps.googleusercontent.com",
                display_name=generation_a.display_name,
                gmail=generation_a.gmail,
            ),
        )
        storage_type = EncryptedOAuthStorage
        original_get = storage_type.get_sync
        advanced = False

        def advance_after_snapshot(
            target: EncryptedOAuthStorage, *args: object, **kwargs: object
        ) -> dict[str, object] | None:
            nonlocal advanced
            result = original_get(target, *args, **kwargs)
            if not advanced:
                advanced = True
                generation_c = connections.update_google_connection_for_authority(
                    owner,
                    generation_a.connection_id,
                    GoogleConnectionUpdate(
                        client_id="superseded-c.apps.googleusercontent.com",
                        display_name=generation_a.display_name,
                        gmail=generation_a.gmail,
                    ),
                )
                google.set_client_secret(
                    owner, "superseded-secret-c", generation_c.connection_id
                )
                google.save_token_state(
                    owner,
                    GoogleOAuthTokenState(
                        access_token="superseded-access-c",
                        refresh_token="superseded-refresh-c",
                        scopes=(GMAIL_READONLY_SCOPE,),
                        account_id="superseded-account-c",
                        account_email="superseded-c@example.com",
                    ),
                    generation_c.connection_id,
                )
                credential_c = google.resolve_client_credential(
                    owner, generation_c.connection_id
                )
                if credential_c is None:
                    raise AssertionError("Newest test credential was not stored.")
                EncryptedOAuthStorage(
                    secrets=secrets,
                    authority=owner,
                    namespace=f"oauth.google.{generation_c.connection_id}",
                ).put_sync(
                    "pending-authorization",
                    {
                        "state": "superseded-state-c",
                        "oauth_generation": credential_c.oauth_generation,
                        "credential_id": credential_c.credential_id,
                    },
                    collection="google",
                )
            return result

        with patch.object(storage_type, "get_sync", advance_after_snapshot):
            google.handle_metadata_update(owner, generation_a, generation_b)
        self.soft_assert_equal(
            (
                google.resolve_client_secret(owner, generation_a.connection_id),
                google.load_token_state(owner, generation_a.connection_id).access_token,
                EncryptedOAuthStorage(
                    secrets=secrets,
                    authority=owner,
                    namespace=f"oauth.google.{generation_a.connection_id}",
                ).get_sync("pending-authorization", collection="google")["state"],
            ),
            ("superseded-secret-c", "superseded-access-c", "superseded-state-c"),
            "Superseded metadata cleanup must preserve the newest credential",
        )

    def _assert_oauth_start_rejects_concurrent_changes(
        self,
        *,
        connections: BuiltInConnectionService,
        secrets: EncryptedSecretsService,
        google: GoogleConnectionService,
        owner: ExecutionAuthority,
        redirect_uri: str,
    ) -> None:
        connection = connections.create_google_connection_for_authority(
            owner,
            GoogleConnectionCreate(
                display_name="OAuth start race",
                client_id="oauth-start-a.apps.googleusercontent.com",
            ),
        )
        google.set_client_secret(owner, "oauth-start-secret", connection.connection_id)
        coordinator = GoogleOAuthCoordinator(
            connections=connections,
            google=google,
            secrets=secrets,
        )
        original_put = EncryptedOAuthStorage.put_sync_if_unchanged
        advanced = False

        def advance_after_pending_write(
            target: EncryptedOAuthStorage, *args: object, **kwargs: object
        ) -> float | None:
            nonlocal advanced
            result = original_put(target, *args, **kwargs)
            if not advanced:
                advanced = True
                connections.update_google_connection_for_authority(
                    owner,
                    connection.connection_id,
                    GoogleConnectionUpdate(
                        client_id="oauth-start-b.apps.googleusercontent.com",
                        display_name=connection.display_name,
                        gmail=connection.gmail,
                    ),
                )
            return result

        with patch.object(
            EncryptedOAuthStorage,
            "put_sync_if_unchanged",
            advance_after_pending_write,
        ):
            try:
                coordinator.start(
                    authority=owner,
                    redirect_uri=redirect_uri,
                    capabilities=(GoogleCapability.GMAIL_READ,),
                    connection_id=connection.connection_id,
                )
            except GoogleOAuthError:
                pass
            else:
                self.soft_assert(False, "OAuth start must reject a metadata race")
        pending = EncryptedOAuthStorage(
            secrets=secrets,
            authority=owner,
            namespace=f"oauth.google.{connection.connection_id}",
        ).get_sync("pending-authorization", collection="google")
        self.soft_assert_equal(
            pending,
            None,
            "Rejected OAuth start must conditionally remove its pending state",
        )
        credential_race = connections.create_google_connection_for_authority(
            owner,
            GoogleConnectionCreate(
                display_name="OAuth start credential race",
                client_id="oauth-start-credential.apps.googleusercontent.com",
            ),
        )
        google.set_client_secret(
            owner, "oauth-start-old-secret", credential_race.connection_id
        )
        replaced = False

        def replace_before_pending_write(
            target: EncryptedOAuthStorage, *args: object, **kwargs: object
        ) -> float | None:
            nonlocal replaced
            if not replaced:
                replaced = True
                google.set_client_secret(
                    owner, "oauth-start-new-secret", credential_race.connection_id
                )
            return original_put(target, *args, **kwargs)

        with patch.object(
            EncryptedOAuthStorage,
            "put_sync_if_unchanged",
            replace_before_pending_write,
        ):
            try:
                coordinator.start(
                    authority=owner,
                    redirect_uri=redirect_uri,
                    capabilities=(GoogleCapability.GMAIL_READ,),
                    connection_id=credential_race.connection_id,
                )
            except GoogleOAuthError:
                pass
            else:
                self.soft_assert(False, "OAuth start must reject a credential race")
        credential_pending = EncryptedOAuthStorage(
            secrets=secrets,
            authority=owner,
            namespace=f"oauth.google.{credential_race.connection_id}",
        ).get_sync("pending-authorization", collection="google")
        self.soft_assert_equal(
            (
                google.resolve_client_secret(owner, credential_race.connection_id),
                credential_pending,
            ),
            ("oauth-start-new-secret", None),
            "Credential CAS must reject pending state bound to an old secret",
        )
        post_write = connections.create_google_connection_for_authority(
            owner,
            GoogleConnectionCreate(
                display_name="OAuth start post-write credential race",
                client_id="oauth-start-post-write.apps.googleusercontent.com",
            ),
        )
        google.set_client_secret(owner, "post-write-a", post_write.connection_id)
        replaced_after_write = False

        def replace_after_pending_write(
            target: EncryptedOAuthStorage, *args: object, **kwargs: object
        ) -> float | None:
            nonlocal replaced_after_write
            result = original_put(target, *args, **kwargs)
            if not replaced_after_write:
                replaced_after_write = True
                google.set_client_secret(
                    owner, "post-write-b", post_write.connection_id
                )
            return result

        with patch.object(
            EncryptedOAuthStorage,
            "put_sync_if_unchanged",
            replace_after_pending_write,
        ):
            try:
                coordinator.start(
                    authority=owner,
                    redirect_uri=redirect_uri,
                    capabilities=(GoogleCapability.GMAIL_READ,),
                    connection_id=post_write.connection_id,
                )
            except GoogleOAuthError:
                pass
            else:
                self.soft_assert(
                    False, "OAuth start must reject post-write credential replacement"
                )
        self.soft_assert_equal(
            EncryptedOAuthStorage(
                secrets=secrets,
                authority=owner,
                namespace=f"oauth.google.{post_write.connection_id}",
            ).get_sync("pending-authorization", collection="google"),
            None,
            "Post-write credential replacement must leave no stale pending state",
        )
        disconnect_race = connections.create_google_connection_for_authority(
            owner,
            GoogleConnectionCreate(
                display_name="OAuth start post-write disconnect race",
                client_id="oauth-start-disconnect.apps.googleusercontent.com",
            ),
        )
        google.set_client_secret(
            owner, "post-write-disconnect", disconnect_race.connection_id
        )
        disconnected_after_write = False

        def disconnect_after_pending_write(
            target: EncryptedOAuthStorage, *args: object, **kwargs: object
        ) -> float | None:
            nonlocal disconnected_after_write
            result = original_put(target, *args, **kwargs)
            if not disconnected_after_write:
                disconnected_after_write = True
                google.clear_token_state(owner, disconnect_race.connection_id)
            return result

        with patch.object(
            EncryptedOAuthStorage,
            "put_sync_if_unchanged",
            disconnect_after_pending_write,
        ):
            try:
                coordinator.start(
                    authority=owner,
                    redirect_uri=redirect_uri,
                    capabilities=(GoogleCapability.GMAIL_READ,),
                    connection_id=disconnect_race.connection_id,
                )
            except GoogleOAuthError:
                pass
            else:
                self.soft_assert(False, "OAuth start must reject a raced disconnect")

        competing = connections.create_google_connection_for_authority(
            owner,
            GoogleConnectionCreate(
                display_name="Competing OAuth starts",
                client_id="competing-oauth-starts.apps.googleusercontent.com",
            ),
        )
        google.set_client_secret(owner, "competing-secret", competing.connection_id)
        nested_start: list[GoogleOAuthStart] = []
        launched_competitor = False

        def launch_competing_start(
            target: EncryptedOAuthStorage, *args: object, **kwargs: object
        ) -> float | None:
            nonlocal launched_competitor
            result = original_put(target, *args, **kwargs)
            if not launched_competitor:
                launched_competitor = True
                nested_start.append(
                    coordinator.start(
                        authority=owner,
                        redirect_uri=redirect_uri,
                        capabilities=(GoogleCapability.GMAIL_READ,),
                        connection_id=competing.connection_id,
                    )
                )
            return result

        with patch.object(
            EncryptedOAuthStorage,
            "put_sync_if_unchanged",
            launch_competing_start,
        ):
            try:
                coordinator.start(
                    authority=owner,
                    redirect_uri=redirect_uri,
                    capabilities=(GoogleCapability.GMAIL_READ,),
                    connection_id=competing.connection_id,
                )
            except GoogleOAuthError:
                pass
            else:
                self.soft_assert(False, "A superseded OAuth start must fail")
        surviving_pending = EncryptedOAuthStorage(
            secrets=secrets,
            authority=owner,
            namespace=f"oauth.google.{competing.connection_id}",
        ).get_sync("pending-authorization", collection="google")
        nested_state = parse_qs(urlparse(nested_start[0].authorization_url).query)[
            "state"
        ][0]
        self.soft_assert_equal(
            surviving_pending["state"] if surviving_pending is not None else None,
            nested_state,
            "A superseded start must not delete the newer pending attempt",
        )

    def _assert_default_deletion_clears_legacy_before_promotion(
        self,
        *,
        connections: BuiltInConnectionService,
        secrets: EncryptedSecretsService,
        google: GoogleConnectionService,
    ) -> None:
        authority = ExecutionAuthority("legacy-default-delete-owner")
        default = connections.create_google_connection_for_authority(
            authority,
            GoogleConnectionCreate(
                display_name="Legacy Default",
                client_id="legacy-default.apps.googleusercontent.com",
            ),
        )
        replacement = connections.create_google_connection_for_authority(
            authority,
            GoogleConnectionCreate(
                display_name="Legacy Replacement",
                client_id="legacy-replacement.apps.googleusercontent.com",
            ),
        )
        EncryptedOAuthStorage(
            secrets=secrets,
            authority=authority,
            namespace="oauth.google",
        ).put_sync(
            "client-secret",
            {"value": "unbound-legacy-secret"},
            collection="google",
        )
        google.clear_legacy_state(authority)
        connections.delete_google_connection_for_authority(
            authority,
            default.connection_id,
            replacement_default_id=replacement.connection_id,
        )
        google.reconcile_connection_deletion(authority, default.connection_id)
        self.soft_assert_equal(
            google.resolve_client_secret(authority, replacement.connection_id),
            None,
            "Default promotion must not inherit the deleted connection's legacy secret",
        )


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


def _blocking_oauth_client(
    requests: list[httpx.Request],
    *,
    entered: asyncio.Event,
    release: asyncio.Event,
    blocked_step: str,
) -> httpx.AsyncClient:
    async def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        is_refresh = b"grant_type=refresh_token" in request.content
        should_block = (
            (blocked_step == "identity" and request.url.path.endswith("/v1/userinfo"))
            or (
                blocked_step == "token"
                and request.url.path.endswith("/token")
                and not is_refresh
            )
            or (blocked_step == "refresh" and is_refresh)
        )
        if should_block:
            entered.set()
            await release.wait()
        if request.url.path.endswith("/token"):
            if is_refresh:
                return httpx.Response(
                    200,
                    json={
                        "access_token": "raced-refreshed-access-token",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                    },
                )
            return httpx.Response(
                200,
                json={
                    "access_token": "raced-initial-access-token",
                    "refresh_token": "raced-initial-refresh-token",
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
                json={"sub": "raced-account", "email": "raced@example.com"},
            )
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(respond))


if __name__ == "__main__":
    asyncio.run(GoogleOAuthCoordinatorScenario().test_scenario())
