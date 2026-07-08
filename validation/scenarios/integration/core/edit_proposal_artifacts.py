"""Integration scenario for collaborative edit proposal artifacts."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from core.chat.chat_store import ChatStore
from core.tools.propose_file_edits import ProposeFileEditsTool
from validation.core.base_scenario import BaseScenario


class EditProposalArtifactsScenario(BaseScenario):
    """Validate edit proposal artifact creation, API fetch, apply, and conflict handling."""

    async def test_scenario(self):
        vault = self.create_vault("EditProposalArtifactsVault")
        self.create_file(
            vault,
            "Projects/Alpha/README.md",
            "# Alpha\n\nStatus: Draft\n\nNext: Write summary.\n",
        )

        await self.start_system()

        session_id = "edit_proposal_artifacts_session"
        store = ChatStore(system_root=str(self._get_system_controller()._system_root))
        store.ensure_session(session_id, vault.name)

        tool = ProposeFileEditsTool.get_tool(vault_path=str(vault))
        create_checkpoint = self.event_checkpoint()
        result = await tool.function(
            SimpleNamespace(deps=SimpleNamespace(vault_name=vault.name, session_id=session_id)),
            edits=[
                {
                    "path": "Projects/Alpha/README.md",
                    "original_text": "Status: Draft",
                    "replacement_text": "Status: Reviewed",
                    "rationale": "Mark the note as reviewed.",
                }
            ],
            title="Review README status",
            summary="One focused status update.",
        )
        assert result.metadata["artifact_ref"], "Proposal tool should return an artifact ref"
        artifact_ref = result.metadata["artifact_ref"]
        self.assert_event_contains(
            self.events_since(create_checkpoint),
            name="edit_proposal_created",
            expected={
                "vault_name": vault.name,
                "session_id": session_id,
                "artifact_ref": artifact_ref,
                "edit_count": 1,
            },
        )

        fetched = self.call_api(
            f"/api/vaults/{vault.name}/chat/{session_id}/edit-proposals/{artifact_ref}"
        )
        assert fetched.status_code == 200, "Stored proposal should be fetchable through the API"
        proposal = fetched.json()
        assert proposal["artifact_ref"] == artifact_ref, "Fetched proposal should preserve artifact ref"
        assert proposal["status"] == "pending", "New proposal should start pending"
        assert proposal["edits"][0]["before_sha256"], "Proposal should capture the pre-edit file hash"

        apply_checkpoint = self.event_checkpoint()
        applied = self.call_api(
            f"/api/vaults/{vault.name}/chat/{session_id}/edit-proposals/{artifact_ref}/apply",
            method="POST",
            data={
                "selected_edit_ids": [proposal["edits"][0]["edit_id"]],
                "replacement_overrides": {
                    proposal["edits"][0]["edit_id"]: "Status: Approved",
                },
            },
        )
        assert applied.status_code == 200, "Selected proposal edits should apply"
        assert applied.json()["status"] == "applied", "Apply response should mark proposal applied"
        assert (vault / "Projects/Alpha/README.md").read_text(encoding="utf-8") == (
            "# Alpha\n\nStatus: Approved\n\nNext: Write summary.\n"
        ), "Apply should write the user-edited replacement text"

        self.assert_event_contains(
            self.events_since(apply_checkpoint),
            name="vault_state_mutation_untracked",
            expected={
                "vault_name": vault.name,
                "path": "Projects/Alpha/README.md",
                "operation": "apply_edit_proposal",
                "reason": "missing_execution_task_context",
            },
        )

        second = self.call_api(
            f"/api/vaults/{vault.name}/chat/{session_id}/edit-proposals/{artifact_ref}/apply",
            method="POST",
            data={"selected_edit_ids": [proposal["edits"][0]["edit_id"]]},
        )
        assert second.status_code == 409, "Already-applied proposal should reject repeated apply"
        assert second.json().get("error") == "ProposalAlreadyApplied", (
            "Repeated apply should use a stable conflict error"
        )

        conflict_result = await tool.function(
            SimpleNamespace(deps=SimpleNamespace(vault_name=vault.name, session_id=session_id)),
            edits=[
                {
                    "path": "Projects/Alpha/README.md",
                    "original_text": "Next: Write summary.",
                    "replacement_text": "Next: Publish summary.",
                }
            ],
        )
        conflict_ref = conflict_result.metadata["artifact_ref"]
        (vault / "Projects/Alpha/README.md").write_text(
            "# Alpha\n\nStatus: Approved\n\nNext: Changed elsewhere.\n",
            encoding="utf-8",
        )
        conflict_proposal = self.call_api(
            f"/api/vaults/{vault.name}/chat/{session_id}/edit-proposals/{conflict_ref}"
        ).json()
        conflict = self.call_api(
            f"/api/vaults/{vault.name}/chat/{session_id}/edit-proposals/{conflict_ref}/apply",
            method="POST",
            data={"selected_edit_ids": [conflict_proposal["edits"][0]["edit_id"]]},
        )
        assert conflict.status_code == 409, "Changed file should reject stale proposal apply"
        assert conflict.json().get("error") == "VaultFileConflict", (
            "Stale proposal apply should use the vault conflict error"
        )

        deny_result = await tool.function(
            SimpleNamespace(deps=SimpleNamespace(vault_name=vault.name, session_id=session_id)),
            edits=[
                {
                    "path": "Projects/Alpha/README.md",
                    "original_text": "Status: Approved",
                    "replacement_text": "Status: Rejected",
                }
            ],
        )
        deny_ref = deny_result.metadata["artifact_ref"]
        deny_checkpoint = self.event_checkpoint()
        denied = self.call_api(
            f"/api/vaults/{vault.name}/chat/{session_id}/edit-proposals/{deny_ref}/deny",
            method="POST",
        )
        assert denied.status_code == 200, "Proposal deny should succeed without writing files"
        assert denied.json().get("status") == "denied", "Deny response should mark proposal denied"
        assert (vault / "Projects/Alpha/README.md").read_text(encoding="utf-8") == (
            "# Alpha\n\nStatus: Approved\n\nNext: Changed elsewhere.\n"
        ), "Deny should not mutate the target file"
        self.assert_event_contains(
            self.events_since(deny_checkpoint),
            name="edit_proposal_denied",
            expected={
                "vault_name": vault.name,
                "session_id": session_id,
                "artifact_ref": deny_ref,
            },
        )

        denied_proposal = self.call_api(
            f"/api/vaults/{vault.name}/chat/{session_id}/edit-proposals/{deny_ref}"
        ).json()
        denied_apply = self.call_api(
            f"/api/vaults/{vault.name}/chat/{session_id}/edit-proposals/{deny_ref}/apply",
            method="POST",
            data={"selected_edit_ids": [denied_proposal["edits"][0]["edit_id"]]},
        )
        assert denied_apply.status_code == 409, "Denied proposal should not be applicable"
        assert denied_apply.json().get("error") == "ProposalDenied", (
            "Denied proposal apply should use a stable conflict error"
        )
