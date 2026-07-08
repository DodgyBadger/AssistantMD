"""Integration scenario for chat-native vault file reference API contracts."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation.core.base_scenario import BaseScenario


class VaultFileReferenceApiScenario(BaseScenario):
    """Validate vault file reference listing, inline read/write, and mutation audit."""

    async def test_scenario(self):
        vault = self.create_vault("VaultFileReferenceApiVault")
        self.create_file(vault, "Projects/Alpha/README.md", "# Alpha\n\nStart here.\n")
        self.create_file(vault, "Projects/Alpha/notes.txt", "plain notes\n")
        self.create_file(vault, "Projects/Alpha/Nested/plan.md", "# Plan\n")
        self.create_file(vault, ".hidden/secret.md", "hidden\n")

        await self.start_system()

        refs = self.call_api(
            f"/api/vaults/{vault.name}/file-refs",
            params={"workspace_path": "Projects", "scope": "workspace", "limit": 20},
        )
        assert refs.status_code == 200, "File reference listing should succeed"
        refs_payload = refs.json()
        paths = {item["path"] for item in refs_payload.get("items", [])}
        assert "Projects/Alpha" in paths, "Workspace listing should include project folders"
        assert ".hidden/secret.md" not in paths, "Workspace listing should not expose hidden paths"

        search = self.call_api(
            f"/api/vaults/{vault.name}/file-refs",
            params={
                "workspace_path": "Projects",
                "scope": "vault",
                "query": "readme",
                "limit": 20,
            },
        )
        assert search.status_code == 200, "Vault-wide file reference search should succeed"
        search_paths = {item["path"] for item in search.json().get("items", [])}
        assert "Projects/Alpha/README.md" in search_paths, "Search should find markdown files"
        assert ".hidden/secret.md" not in search_paths, "Search should not expose hidden files"

        read = self.call_api(
            f"/api/vaults/{vault.name}/files",
            params={"path": "Projects/Alpha/README.md"},
        )
        assert read.status_code == 200, "Vault file read should succeed"
        read_payload = read.json()
        assert read_payload["content"] == "# Alpha\n\nStart here.\n", "Read returns exact content"
        assert read_payload["sha256"], "Read returns a content hash"

        traversal = self.call_api(
            f"/api/vaults/{vault.name}/files",
            params={"path": "../outside.md"},
        )
        assert traversal.status_code == 400, "Traversal path should be rejected"
        assert traversal.json().get("error") == "InvalidVaultFilePath", (
            "Traversal rejection should use stable API error type"
        )

        stale = self.call_api(
            f"/api/vaults/{vault.name}/files",
            method="PUT",
            params={"path": "Projects/Alpha/README.md"},
            data={"content": "# Changed\n", "expected_sha256": "stale"},
        )
        assert stale.status_code == 409, "Stale hash should reject save"
        assert stale.json().get("error") == "VaultFileConflict", (
            "Stale hash should use conflict error type"
        )
        assert (vault / "Projects/Alpha/README.md").read_text(encoding="utf-8") == (
            "# Alpha\n\nStart here.\n"
        ), "Stale save must not modify the file"

        mutation_checkpoint = self.event_checkpoint()
        update = self.call_api(
            f"/api/vaults/{vault.name}/files",
            method="PUT",
            params={"path": "Projects/Alpha/README.md"},
            data={
                "content": "# Alpha\n\nUpdated.\n",
                "expected_sha256": read_payload["sha256"],
            },
        )
        assert update.status_code == 200, "Hash-matched save should succeed"
        update_hash = update.json()["sha256"]
        assert update_hash != read_payload["sha256"], "Save should return the new content hash"
        assert (vault / "Projects/Alpha/README.md").read_text(encoding="utf-8") == (
            "# Alpha\n\nUpdated.\n"
        ), "Hash-matched save should update the file"
        update_events = self.events_since(mutation_checkpoint)
        self.assert_event_contains(
            update_events,
            name="vault_state_mutation_untracked",
            expected={
                "vault_name": vault.name,
                "path": "Projects/Alpha/README.md",
                "operation": "update_vault_file",
                "reason": "missing_execution_task_context",
            },
        )

        missing = self.call_api(
            f"/api/vaults/{vault.name}/files",
            params={"path": "Projects/README.md"},
        )
        assert missing.status_code == 404, "Missing referenced file should report not found"
        assert missing.json().get("error") == "VaultFileNotFound", (
            "Missing referenced file should use stable not-found error"
        )

        create = self.call_api(
            f"/api/vaults/{vault.name}/files",
            method="PUT",
            params={"path": "Projects/README.md"},
            data={
                "content": "# Projects\n\nWorkspace landing page.\n",
                "create_if_missing": True,
            },
        )
        assert create.status_code == 200, "Create-if-missing save should succeed"
        assert create.json()["content"] == "# Projects\n\nWorkspace landing page.\n", (
            "Create response should return the created content"
        )
        assert (vault / "Projects/README.md").read_text(encoding="utf-8") == (
            "# Projects\n\nWorkspace landing page.\n"
        ), "Create-if-missing should write the new vault file"

        vault_events = self._vault_file_events()
        event_hashes = {row["path"]: row["content_hash"] for row in vault_events}
        assert event_hashes.get("Projects/Alpha/README.md") == update_hash, (
            "Inline file edit should refresh vault-state with the edited content hash"
        )
        event_pairs = {(row["event_type"], row["path"]) for row in vault_events}
        assert ("created", "Projects/README.md") in event_pairs, (
            "Create-if-missing should refresh vault-state creation events"
        )

    def _vault_file_events(self) -> list[sqlite3.Row]:
        db_path = self.run_path / "system" / "vault_state.db"
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        try:
            return list(
                connection.execute(
                    """
                    SELECT event_type, path, content_hash
                    FROM vault_file_events
                    ORDER BY sequence
                    """
                )
            )
        finally:
            connection.close()
