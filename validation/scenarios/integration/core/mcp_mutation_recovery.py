"""Recovery contracts for durable cross-database MCP mutations."""

from __future__ import annotations

import asyncio
import sqlite3
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

_direct_run_root: tempfile.TemporaryDirectory[str] | None = None
if __name__ == "__main__":
    from core.runtime.paths import set_bootstrap_roots

    _direct_run_root = tempfile.TemporaryDirectory(prefix="assistantmd-mcp-saga-")
    direct_root = Path(_direct_run_root.name)
    data_root = direct_root / "data"
    bootstrap_system_root = direct_root / "system"
    data_root.mkdir()
    bootstrap_system_root.mkdir()
    set_bootstrap_roots(data_root=data_root, system_root=bootstrap_system_root)

from core.identity import ExecutionAuthority, use_execution_authority  # noqa: E402
from core.mcp import (  # noqa: E402
    MCPAuthMode,
    MCPConnectionCreate,
    MCPConnectionService,
    MCPConnectionUpdate,
    MCPTransport,
)
from core.secrets import (  # noqa: E402
    EncryptedSecretsService,
    SecretGuardMismatchError,
    SecretKeyring,
)
from core.system_migrations import run_system_migrations  # noqa: E402
from validation.core.base_scenario import BaseScenario  # noqa: E402


class _OneShotFailure:
    def __init__(self, boundary: str) -> None:
        self.boundary = boundary
        self.fired = False

    def __call__(self, boundary: str, _operation_id: str) -> None:
        if boundary == self.boundary and not self.fired:
            self.fired = True
            raise RuntimeError(f"injected {boundary} failure")


class _SimulatedProcessCrash(BaseException):
    """Bypass ordinary exception cleanup to model process termination."""


class _CrashAfterStage:
    def __call__(self, boundary: str, _operation_id: str) -> None:
        if boundary == "after_stage":
            raise _SimulatedProcessCrash


class MCPMutationRecoveryScenario(BaseScenario):
    """Prove MCP mutations converge exactly once after durable-boundary failures."""

    async def test_scenario(self) -> None:
        owner = ExecutionAuthority("mcp-saga-owner")
        system_root = self.run_path / "system"
        system_root.mkdir()
        run_system_migrations(system_root, backup=False)
        secrets = EncryptedSecretsService(
            system_root=str(system_root),
            keyring=SecretKeyring(keys={1: bytes(range(32))}, active_version=1),
        )

        crashed_before_intent = MCPConnectionService(
            system_root=str(system_root),
            secrets=secrets,
            mutation_failpoint=_CrashAfterStage(),
        )
        try:
            crashed_before_intent.create_connection_for_authority(
                owner,
                MCPConnectionCreate(
                    display_name="Never committed",
                    url="https://never-committed.example/mcp",
                    auth_mode=MCPAuthMode.BEARER,
                    credential="orphan-stage-token",
                ),
            )
        except _SimulatedProcessCrash:
            pass
        else:
            self.soft_assert(False, "The process-crash failpoint should terminate")
        with sqlite3.connect(system_root / "mcp.db") as conn:
            staging_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM mcp_connection_mutations
                    WHERE state = 'staging'
                    """
                ).fetchone()[0]
            )
        self.soft_assert_equal(
            staging_count,
            1,
            "Pre-intent staging must have a durable cleanup record",
        )
        staging_recovery = MCPConnectionService(
            system_root=str(system_root), secrets=secrets
        )
        self.soft_assert_equal(
            staging_recovery.reconcile_pending_mutations(),
            1,
            "Startup should reconcile a process death before intent commit",
        )
        self.soft_assert(
            not any(
                item.namespace.startswith("mcp.mutation.")
                for item in secrets.list_metadata_for_authority(owner)
            ),
            "Pre-intent crash recovery must remove encrypted staging records",
        )
        self.soft_assert_equal(
            staging_recovery.list_connections_for_authority(owner),
            [],
            "Pre-intent crash recovery must preserve the prior absent state",
        )

        create_failure = _OneShotFailure("after_intent")
        interrupted_create = MCPConnectionService(
            system_root=str(system_root),
            secrets=secrets,
            mutation_failpoint=create_failure,
        )
        try:
            interrupted_create.create_connection_for_authority(
                owner,
                MCPConnectionCreate(
                    display_name="Recovered",
                    url="https://recovered.example/mcp",
                    auth_mode=MCPAuthMode.BEARER,
                    credential="recovered-token",
                ),
            )
        except RuntimeError:
            pass
        else:
            self.soft_assert(False, "The create failpoint should interrupt the request")
        self.soft_assert_equal(
            interrupted_create.list_connections_for_authority(owner),
            [],
            "A pending create must remain unavailable to runtime listings",
        )

        recovered = MCPConnectionService(system_root=str(system_root), secrets=secrets)
        self.soft_assert_equal(
            recovered.reconcile_pending_mutations(),
            1,
            "Startup reconciliation should recover the durable create intent",
        )
        created = recovered.list_connections_for_authority(owner)[0]
        self.soft_assert_equal(
            (
                created.config_version,
                recovered.resolve_credential(owner, created.connection_id),
                recovered.reconcile_pending_mutations(),
            ),
            (1, "recovered-token", 0),
            "Create recovery should preserve version one and be idempotent",
        )

        concurrent_failure = _OneShotFailure("after_secrets_applied")
        interrupted_credential = MCPConnectionService(
            system_root=str(system_root),
            secrets=secrets,
            mutation_failpoint=concurrent_failure,
        )
        with use_execution_authority(owner):
            try:
                interrupted_credential.set_credential(
                    created.connection_id, "concurrently-recovered-token"
                )
            except RuntimeError:
                pass
            else:
                self.soft_assert(
                    False, "The secrets-applied failpoint should interrupt the request"
                )
        reconcilers = (
            MCPConnectionService(system_root=str(system_root), secrets=secrets),
            MCPConnectionService(system_root=str(system_root), secrets=secrets),
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(service.reconcile_pending_mutations)
                for service in reconcilers
            ]
            for future in futures:
                future.result()
        concurrent_connection = recovered.get_connection_for_authority(
            owner, created.connection_id
        )
        self.soft_assert(
            concurrent_connection is not None,
            "Concurrent reconcilers should converge the pending credential update",
        )
        if concurrent_connection is not None:
            self.soft_assert_equal(
                (
                    concurrent_connection.config_version,
                    recovered.resolve_credential(owner, created.connection_id),
                ),
                (created.config_version + 1, "concurrently-recovered-token"),
                "Concurrent reconciliation should finalize one version increment",
            )

        with use_execution_authority(owner):
            oauth_connection = recovered.create_connection(
                MCPConnectionCreate(
                    display_name="OAuth server",
                    url="https://oauth.example/mcp",
                    auth_mode=MCPAuthMode.OAUTH,
                    oauth_client_id="client-a",
                    oauth_client_secret="client-secret",
                    oauth_scopes=("read",),
                )
            )
        stale_storage = recovered.oauth_storage(owner, oauth_connection.connection_id)
        await stale_storage.put("token", {"access_token": "old-token"})

        update_failure = _OneShotFailure("after_secret_effects")
        interrupted_update = MCPConnectionService(
            system_root=str(system_root),
            secrets=secrets,
            mutation_failpoint=update_failure,
        )
        with use_execution_authority(owner):
            try:
                interrupted_update.update_connection(
                    oauth_connection.connection_id,
                    MCPConnectionUpdate(
                        display_name="OAuth server",
                        url="https://oauth.example/v2/mcp",
                        transport=MCPTransport.STREAMABLE_HTTP,
                        auth_mode=MCPAuthMode.OAUTH,
                        header_name=None,
                        enabled=True,
                        allow_private_http=False,
                        allowed_tools=None,
                        oauth_client_id="client-b",
                        oauth_scopes=("read", "write"),
                    ),
                )
            except RuntimeError:
                pass
            else:
                self.soft_assert(
                    False, "The update failpoint should interrupt the request"
                )
        try:
            await stale_storage.put("late", {"access_token": "stale-token"})
        except SecretGuardMismatchError:
            pass
        else:
            self.soft_assert(False, "A rotated OAuth fence must reject stale writers")
        self.soft_assert_equal(
            interrupted_update.get_connection_for_authority(
                owner, oauth_connection.connection_id
            ),
            None,
            "A partially applied update must remain unavailable",
        )

        recovered_update = MCPConnectionService(
            system_root=str(system_root), secrets=secrets
        )
        recovered_update.reconcile_pending_mutations()
        updated = recovered_update.get_connection_for_authority(
            owner, oauth_connection.connection_id
        )
        self.soft_assert(
            updated is not None,
            "Update reconciliation should restore the connection to active state",
        )
        if updated is not None:
            self.soft_assert_equal(
                (updated.config_version, updated.oauth_client_id, updated.oauth_scopes),
                (oauth_connection.config_version + 1, "client-b", ("read", "write")),
                "Update recovery should finalize desired metadata exactly once",
            )
        self.soft_assert_equal(
            await recovered_update.oauth_storage(
                owner, oauth_connection.connection_id
            ).get("token"),
            None,
            "OAuth-sensitive metadata changes should clear prior OAuth state",
        )

        finalize_failure = _OneShotFailure("after_finalize")
        interrupted_secret = MCPConnectionService(
            system_root=str(system_root),
            secrets=secrets,
            mutation_failpoint=finalize_failure,
        )
        with use_execution_authority(owner):
            try:
                interrupted_secret.set_oauth_client_secret(
                    oauth_connection.connection_id, "replacement-secret"
                )
            except RuntimeError:
                pass
            else:
                self.soft_assert(
                    False, "The finalize failpoint should interrupt the request"
                )
        with sqlite3.connect(system_root / "mcp.db") as conn:
            finalized_version = int(
                conn.execute(
                    "SELECT config_version FROM mcp_connections WHERE connection_id = ?",
                    (oauth_connection.connection_id,),
                ).fetchone()[0]
            )
        recovered_secret = MCPConnectionService(
            system_root=str(system_root), secrets=secrets
        )
        recovered_secret.reconcile_pending_mutations()
        secret_connection = recovered_secret.get_connection_for_authority(
            owner, oauth_connection.connection_id
        )
        self.soft_assert(
            secret_connection is not None,
            "Finalized secret replacement should become visible after journal cleanup",
        )
        if secret_connection is not None:
            self.soft_assert_equal(
                (secret_connection.config_version, finalized_version),
                (finalized_version, finalized_version),
                "Finalized replay must not increment the version twice",
            )

        disconnect_storage = recovered_secret.oauth_storage(
            owner, oauth_connection.connection_id
        )
        await disconnect_storage.put("disconnect-token", {"access_token": "token"})
        disconnected = recovered_secret.disconnect_oauth(
            owner, oauth_connection.connection_id
        )
        try:
            await disconnect_storage.put("late-disconnect", {"access_token": "late"})
        except SecretGuardMismatchError:
            pass
        else:
            self.soft_assert(
                False, "OAuth disconnect must fence issued storage adapters"
            )
        self.soft_assert_equal(
            (
                disconnected.config_version,
                await recovered_secret.oauth_storage(
                    owner, oauth_connection.connection_id
                ).get("disconnect-token"),
            ),
            (finalized_version + 1, None),
            "OAuth disconnect should clear its namespace and increment once",
        )

        slug = created.slug
        delete_failure = _OneShotFailure("after_finalize")
        interrupted_delete = MCPConnectionService(
            system_root=str(system_root),
            secrets=secrets,
            mutation_failpoint=delete_failure,
        )
        with use_execution_authority(owner):
            try:
                interrupted_delete.delete_connection(created.connection_id)
            except RuntimeError:
                pass
            else:
                self.soft_assert(
                    False, "The delete failpoint should interrupt the request"
                )
        recovered_delete = MCPConnectionService(
            system_root=str(system_root), secrets=secrets
        )
        recovered_delete.reconcile_pending_mutations()
        with sqlite3.connect(system_root / "mcp.db") as conn:
            journal_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM mcp_connection_mutations"
                ).fetchone()[0]
            )
            retained_slug = conn.execute(
                "SELECT slug FROM mcp_connection_slugs WHERE connection_id = ?",
                (created.connection_id,),
            ).fetchone()
        self.soft_assert_equal(
            (journal_count, retained_slug[0] if retained_slug else None),
            (0, slug),
            "Delete recovery should clear its journal while retaining slug reservation",
        )
        self.soft_assert(
            b"recovered-token" not in (system_root / "mcp.db").read_bytes()
            and b"replacement-secret" not in (system_root / "mcp.db").read_bytes(),
            "Mutation metadata must never persist secret plaintext",
        )

        self.assert_no_failures()
        self.teardown_scenario()


if __name__ == "__main__":
    asyncio.run(MCPMutationRecoveryScenario().test_scenario())
